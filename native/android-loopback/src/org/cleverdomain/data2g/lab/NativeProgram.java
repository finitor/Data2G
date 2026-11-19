package org.cleverdomain.data2g.lab;

import android.content.Context;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/** Run the upstream test/tool itself, not a reimplementation of its checks. */
final class NativeProgram {
    static JSONObject run(Context context, JSONObject request, File directory, int pool,
                          TimelineSampler observer, BooleanSupplier cancelled, Consumer<String> progress) throws Exception {
        String id = request.getString("program");
        if (!id.matches("test_[a-z0-9_]+|data2g-replay|data2g-bench-rx")) throw new IllegalArgumentException("Unknown native program");
        File executable = new File(context.getApplicationInfo().nativeLibraryDir, "liblab_" + id + ".so");
        if (!executable.isFile()) throw new IllegalArgumentException("Program not packaged: " + id);
        directory.mkdirs();
        ArrayList<String> command = new ArrayList<>(); command.add(executable.getAbsolutePath());
        JSONArray args = request.optJSONArray("args");
        if (args != null) for (int i = 0; i < args.length(); ++i) command.add(args.getString(i));
        ProcessBuilder builder = new ProcessBuilder(command).directory(directory).redirectErrorStream(true);
        builder.environment().put("TMPDIR", directory.getAbsolutePath());
        builder.environment().put("LD_LIBRARY_PATH", context.getApplicationInfo().nativeLibraryDir);
        builder.environment().put("DATA2G_THREADS", String.valueOf(pool));
        final long started = SystemClock.elapsedRealtimeNanos();
        final Process process = builder.start();
        final ArrayDeque<String> tail = new ArrayDeque<>();
        final JSONObject[] summary = {null};
        final String[] revision = {"unknown"};
        final boolean[] truncated = {false};
        Thread reader = new Thread(() -> {
            try (BufferedReader in = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8));
                 FileOutputStream log = new FileOutputStream(new File(directory, "output.txt"))) {
                String line; long written = 0;
                while ((line = in.readLine()) != null) {
                    byte[] bytes = (line + "\n").getBytes(StandardCharsets.UTF_8);
                    if (written + bytes.length <= 8 * 1024 * 1024) { log.write(bytes); written += bytes.length; }
                    else truncated[0] = true;
                    progress.accept(line);
                    if (line.startsWith("LAB_PID ") && observer != null) observer.beginChild(Integer.parseInt(line.substring(8).trim()));
                    if (line.startsWith("LAB_SUMMARY ")) summary[0] = new JSONObject(line.substring(12));
                    if (line.startsWith("LAB_REVISION ")) revision[0] = line.substring(13).trim();
                    if (tail.size() == 100) tail.removeFirst();
                    tail.addLast(line.length() > 2000 ? line.substring(0, 2000) : line);
                }
            } catch (Exception e) { tail.addLast("Output reader: " + e); }
        }, "native-output");
        reader.start();
        boolean timeout = false;
        try {
            while (!process.waitFor(100, TimeUnit.MILLISECONDS)) {
                if (cancelled.getAsBoolean()) { process.destroyForcibly(); break; }
                if ((SystemClock.elapsedRealtimeNanos() - started) / 1e9 > 900) { timeout = true; process.destroyForcibly(); break; }
            }
            process.waitFor(); reader.join(5000);
        } finally {
            if (process.isAlive()) process.destroyForcibly();
            if (observer != null) observer.endChild(summary[0] == null ? Double.NaN : summary[0].optDouble("cpu_s", Double.NaN));
        }
        int exit = process.exitValue();
        JSONObject result = new JSONObject().put("schema", 1).put("workload_kind", request.getString("workload_kind"))
                .put("program", id).put("channel", id).put("exit_code", exit)
                .put("revision", revision[0])
                .put("outcome", cancelled.getAsBoolean() ? "cancelled" : timeout ? "timeout" : exit == 0 ? (id.startsWith("test_") ? "passed" : "finished") : "failed")
                .put("wall_s", (SystemClock.elapsedRealtimeNanos() - started) / 1e9)
                .put("goodput_applicable", false).put("requested_pool_threads", pool)
                .put("log_file", new File(directory, "output.txt").getAbsolutePath()).put("log_truncated", truncated[0])
                .put("command", new JSONArray(command)).put("output_tail", new JSONArray(tail));
        if (summary[0] != null) {
            JSONObject data = summary[0];
            result.put("native_summary", data).put("process_cpu_s", data.optDouble("cpu_s"))
                    .put("process_lifetime_peak_rss_bytes", data.optLong("peak_rss_bytes"));
        } else result.put("native_summary_missing", true);
        progress.accept(id + ": " + result.getString("outcome"));
        return result;
    }
}

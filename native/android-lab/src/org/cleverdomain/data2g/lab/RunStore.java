package org.cleverdomain.data2g.lab;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.zip.ZipOutputStream;
import android.os.SystemClock;

/** Append per-case results; keep the dashboard bounded even for 55800-case plans. */
final class RunStore {
    final File directory;
    final JSONObject manifest;
    private final ArrayDeque<JSONObject> recent = new ArrayDeque<>();
    private long lastProfileWrite;
    RunStore(File parent, JSONObject configuration, long started, int total) throws Exception {
        directory = new File(parent, "campaign-" + started);
        if (!directory.mkdirs()) throw new IllegalStateException("Cannot create run directory");
        manifest = new JSONObject().put("schema", 3).put("started_utc_ms", started).put("plan", configuration)
                .put("planned_cases", total).put("completed_cases", 0).put("next_case", configuration.getInt("first_case"))
                .put("outcome_counts", new JSONObject()).put("local_case_directory", directory.getAbsolutePath());
    }
    RunStore(File directory) throws Exception {
        this.directory = directory;
        manifest = new JSONObject(read(new File(directory, "manifest.json")));
        manifest.remove("profiling");
        JSONArray prior = manifest.optJSONArray("trials");
        if (prior != null) for (int i = 0; i < prior.length(); ++i) recent.addLast(prior.getJSONObject(i));
        // Recover cases written since the last dashboard checkpoint. Never
        // overwrite an earlier attempt after a crash or interrupted save.
        File index = new File(directory, "index.jsonl");
        if (index.isFile()) {
            recent.clear(); JSONObject counts = new JSONObject(); int attempts = 0;
            long validBytes = 0;
            int next = manifest.getJSONObject("plan").getInt("first_case");
            try (BufferedReader in = new BufferedReader(new FileReader(index))) {
                String line;
                while ((line = in.readLine()) != null) {
                    JSONObject row;
                    try { row = new JSONObject(line); } catch (Exception incompleteLastLine) { break; }
                    JSONObject result = row;
                    if (recent.size() == 3) recent.removeFirst(); recent.addLast(row);
                    String outcome = result.optString("outcome", "unknown");
                    counts.put(outcome, counts.optInt(outcome) + 1);
                    for (String key : new String[]{"base_control_ok", "base_data_ok", "supplied_control_ok", "supplied_data_ok"})
                        if (result.optBoolean(key)) counts.put(key, counts.optInt(key) + 1);
                    next = row.getInt("ordinal") + (outcome.equals("cancelled") ? 0 : 1); ++attempts;
                    validBytes = Math.min(index.length(), validBytes + line.getBytes(StandardCharsets.UTF_8).length + 1);
                }
            }
            try (RandomAccessFile repair = new RandomAccessFile(index, "rw")) { repair.setLength(validBytes); }
            ArrayDeque<JSONObject> full = new ArrayDeque<>();
            for (JSONObject row : recent) full.addLast(new JSONObject(read(new File(directory, row.getString("file")))));
            recent.clear(); recent.addAll(full);
            manifest.put("next_case", next).put("attempted_cases", attempts).put("outcome_counts", counts)
                    .put("completed_cases", next - manifest.getJSONObject("plan").getInt("first_case"));
        }
    }
    synchronized void add(int ordinal, JSONObject result) throws Exception {
        int attempt = manifest.optInt("attempted_cases") + 1;
        String name = String.format(java.util.Locale.US, "case-%06d-attempt-%06d.json", ordinal, attempt);
        while (new File(directory, name).exists()) name = String.format(java.util.Locale.US, "case-%06d-attempt-%06d.json", ordinal, ++attempt);
        result.put("case_ordinal", ordinal);
        write(new File(directory, name), result.toString());
        JSONObject entry = new JSONObject().put("ordinal", ordinal).put("file", name)
                .put("workload_kind", result.optString("workload_kind")).put("channel", result.optString("channel"))
                .put("fixed_mode", result.optString("fixed_mode")).put("seed", result.optLong("seed"))
                .put("snr_db", result.optDouble("snr_db", 0)).put("outcome", result.optString("outcome"));
        for (String key : new String[]{"base_control_ok", "base_data_ok", "supplied_control_ok", "supplied_data_ok"})
            if (result.has(key)) entry.put(key, result.getBoolean(key));
        File index = new File(directory, "index.jsonl");
        try (RandomAccessFile repair = new RandomAccessFile(index, "rw")) {
            if (repair.length() > 0) { repair.seek(repair.length() - 1); if (repair.read() != '\n') repair.write('\n'); }
        }
        try (FileOutputStream out = new FileOutputStream(index, true)) {
            out.write((entry + "\n").getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        }
        if (recent.size() == 3) recent.removeFirst(); recent.addLast(result);
        String outcome = result.optString("outcome", "unknown");
        JSONObject counts = manifest.getJSONObject("outcome_counts"); counts.put(outcome, counts.optInt(outcome) + 1);
        for (String key : new String[]{"base_control_ok", "base_data_ok", "supplied_control_ok", "supplied_data_ok"})
            if (result.optBoolean(key)) counts.put(key, counts.optInt(key) + 1);
        manifest.put("attempted_cases", attempt);
        manifest.put("completed_cases", Math.max(manifest.getInt("completed_cases"), ordinal - manifest.getJSONObject("plan").getInt("first_case") + (outcome.equals("cancelled") ? 0 : 1)));
        manifest.put("next_case", outcome.equals("cancelled") ? ordinal : ordinal + 1);
    }
    synchronized JSONObject snapshot() throws Exception {
        JSONObject out = new JSONObject(manifest.toString());
        out.put("trials", new JSONArray(recent)).put("dashboard_recent_cases_only", true);
        return out;
    }
    synchronized void checkpoint(JSONObject report, File parent, boolean force) throws Exception {
        // Preserve control fields plus the current dashboard, without rewriting
        // the full history after every case. The JSONL index is authoritative.
        Object profile = report.remove("profiling");
        try {
            long now = SystemClock.elapsedRealtime();
            if (profile != null && (force || now - lastProfileWrite >= 30000)) {
                String name = "resources-segment-" + report.optInt("profiling_segment", 1) + ".json";
                write(new File(directory, name), profile.toString());
                manifest.put("profiling_file", name); report.put("profiling_file", name); lastProfileWrite = now;
            } else if (manifest.has("profiling_file")) report.put("profiling_file", manifest.get("profiling_file"));
            write(new File(directory, "manifest.json"), report.toString());
            write(new File(parent, "latest.json"), report.toString());
        } finally { if (profile != null) report.put("profiling", profile); }
    }
    static void write(File file, String json) throws Exception {
        File temporary = new File(file.getParentFile(), file.getName() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(temporary)) { out.write(json.getBytes(StandardCharsets.UTF_8)); out.getFD().sync(); }
        if (!temporary.renameTo(file)) throw new IllegalStateException("Cannot save " + file);
    }
    static String read(File file) throws Exception {
        if (file.length() > 16 * 1024 * 1024) throw new IllegalArgumentException("Report exceeds 16 MiB");
        StringBuilder out = new StringBuilder();
        try (BufferedReader in = new BufferedReader(new FileReader(file))) { String line; while ((line = in.readLine()) != null) out.append(line).append('\n'); }
        return out.toString();
    }
    void export(ZipOutputStream zip, java.io.InputStream template) throws Exception {
        HtmlReport.exportDirectory(directory, snapshot(), template, zip);
    }
}

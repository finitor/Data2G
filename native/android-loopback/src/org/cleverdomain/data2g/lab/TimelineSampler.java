package org.cleverdomain.data2g.lab;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Debug;
import android.os.PowerManager;
import android.os.Process;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.FileReader;
import java.util.ArrayDeque;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/** App-process observations on a monotonic wall clock, independent of virtual audio time. */
final class TimelineSampler {
    private static final int PERIOD_MS = 250, MAX_SAMPLES = 12000;
    private final Context context;
    private final Runnable changed;
    private final ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor();
    private final ArrayDeque<JSONObject> samples = new ArrayDeque<>();
    private final JSONArray markers = new JSONArray();
    private ScheduledFuture<?> future;
    private long origin, lastTime = -1, lastCpu = -1, memoryTime = -1, batteryTime = -1, lastUi;
    private long pss = -1, dirty = -1;
    private Double batteryC;
    private int dropped;
    private double samplingWallMs;
    private String phase = "setup";

    TimelineSampler(Context context, Runnable changed) {
        this.context = context.getApplicationContext();
        this.changed = changed;
    }
    void start() {
        origin = SystemClock.elapsedRealtimeNanos();
        future = executor.scheduleWithFixedDelay(this::sample, 0, PERIOD_MS, TimeUnit.MILLISECONDS);
    }
    private double elapsed() { return (SystemClock.elapsedRealtimeNanos() - origin) / 1e9; }
    synchronized void mark(String name, String event) {
        phase = name;
        try { markers.put(new JSONObject().put("elapsed_s", elapsed()).put("channel", name).put("event", event)); }
        catch (Exception ignored) { }
    }
    private static Long rssBytes() {
        try (BufferedReader in = new BufferedReader(new FileReader("/proc/self/status"))) {
            String line;
            while ((line = in.readLine()) != null)
                if (line.startsWith("VmRSS:")) return Long.parseLong(line.substring(6).trim().split("\\s+")[0]) * 1024L;
        } catch (Exception ignored) { }
        return null;
    }
    private synchronized void sample() {
        final long begin = SystemClock.elapsedRealtimeNanos();
        try {
            final long now = SystemClock.elapsedRealtimeNanos(), cpu = Process.getElapsedCpuTime();
            JSONObject point = new JSONObject().put("elapsed_s", (now - origin) / 1e9)
                    .put("phase", phase).put("process_cpu_ms", cpu);
            double percent = lastTime < 0 || now <= lastTime || cpu < lastCpu ? Double.NaN
                    : (cpu - lastCpu) * 1e8 / (now - lastTime);
            point.put("cpu_one_core_pct", Double.isFinite(percent) ? percent : JSONObject.NULL);
            lastTime = now; lastCpu = cpu;
            Long rss = rssBytes();
            point.put("rss_bytes", rss == null ? JSONObject.NULL : rss);
            // PSS walks memory mappings; keep this more expensive observation
            // to one per second and retain the age of cached values.
            if (memoryTime < 0 || now - memoryTime >= 1000000000L) {
                try {
                    Debug.MemoryInfo memory = new Debug.MemoryInfo();
                    Debug.getMemoryInfo(memory);
                    pss = memory.getTotalPss() * 1024L;
                    dirty = memory.getTotalPrivateDirty() * 1024L;
                    memoryTime = now;
                } catch (RuntimeException ignored) { }
            }
            point.put("pss_bytes", pss < 0 ? JSONObject.NULL : pss)
                    .put("private_dirty_bytes", dirty < 0 ? JSONObject.NULL : dirty)
                    .put("pss_age_ms", memoryTime < 0 ? JSONObject.NULL : (now - memoryTime) / 1000000L);
            try { point.put("thermal_status", context.getSystemService(PowerManager.class).getCurrentThermalStatus()); }
            catch (RuntimeException e) { point.put("thermal_status", JSONObject.NULL); }
            if (batteryTime < 0 || now - batteryTime >= 1000000000L) {
                try {
                    Intent battery = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
                    if (battery != null && battery.hasExtra(BatteryManager.EXTRA_TEMPERATURE)) {
                        batteryC = battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10.0;
                        batteryTime = now;
                    }
                } catch (RuntimeException ignored) { }
            }
            point.put("battery_temperature_c", batteryC == null ? JSONObject.NULL : batteryC)
                    .put("battery_query_age_ms", batteryTime < 0 ? JSONObject.NULL : (now - batteryTime) / 1000000L);
            if (samples.size() == MAX_SAMPLES) { samples.removeFirst(); ++dropped; }
            point.put("sample_work_ms", (SystemClock.elapsedRealtimeNanos() - begin) / 1e6);
            samplingWallMs += point.getDouble("sample_work_ms");
            samples.addLast(point);
            if (now - lastUi >= 1000000000L) { lastUi = now; changed.run(); }
        } catch (Exception ignored) {
            // An unavailable counter becomes a gap, never a fabricated zero.
        }
    }
    void finish() {
        if (future != null) future.cancel(false);
        executor.shutdown();
        try { executor.awaitTermination(5, TimeUnit.SECONDS); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        sample();
    }
    synchronized JSONObject snapshot() {
        try {
            JSONArray copy = new JSONArray();
            for (JSONObject sample : samples) copy.put(sample); // rows are immutable once published
            return new JSONObject().put("schema", 1).put("clock", "monotonic_wall_time")
                    .put("nominal_interval_ms", PERIOD_MS).put("memory_interval_ms", 1000)
                    .put("cpu_convention", "100 percent = one CPU core; app process including sampler and UI")
                    .put("sampling_work_wall_ms", samplingWallMs).put("dropped_oldest_samples", dropped)
                    .put("samples", copy).put("markers", new JSONArray(markers.toString()))
                    .put("limits", new JSONArray().put("battery temperature is not CPU temperature")
                            .put("Android thermal severity is not a direct CPU temperature or frequency measurement")
                            .put("battery values are OS-reported and may update more slowly than sampling")
                            .put("sampled RSS/PSS may miss transient memory peaks; native lifetime RSS peak is recorded separately")
                            .put("sampling and chart work contribute to observed process CPU and memory"));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
}

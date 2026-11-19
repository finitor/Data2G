package org.cleverdomain.data2g.lab;

import android.content.Context;
import android.app.ActivityManager;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Debug;
import android.os.PowerManager;
import android.os.Process;
import android.os.SystemClock;
import android.system.Os;
import android.system.OsConstants;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.File;
import java.io.BufferedWriter;
import java.io.FileWriter;
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
    private final ArrayDeque<JSONObject> markers = new ArrayDeque<>();
    private ScheduledFuture<?> future;
    private long origin, lastTime = -1, lastCpu = -1, memoryTime = -1, batteryTime = -1, lastUi;
    private long pss = -1, dirty = -1;
    private long phoneMemoryTime = -1, phoneTotal = -1, phoneAvailable = -1, phoneThreshold = -1;
    private Boolean phoneLowMemory;
    private Double batteryC;
    private int dropped, droppedMarkers;
    private String journalError = "";
    private double samplingWallMs;
    private String phase = "setup";
    private int childPid;
    private long completedChildCpu, liveChildCpu;
    private final long clockTicks = ticks();
    private BufferedWriter journal;
    private static long ticks() { try { return Os.sysconf(OsConstants._SC_CLK_TCK); } catch (Exception e) { return -1; } }

    TimelineSampler(Context context, Runnable changed) {
        this.context = context.getApplicationContext();
        this.changed = changed;
    }
    TimelineSampler(Context context, Runnable changed, File journalFile) throws Exception {
        this(context, changed);
        journal = new BufferedWriter(new FileWriter(journalFile, true));
    }
    void start() {
        origin = SystemClock.elapsedRealtimeNanos();
        future = executor.scheduleWithFixedDelay(this::sample, 0, PERIOD_MS, TimeUnit.MILLISECONDS);
    }
    private double elapsed() { return (SystemClock.elapsedRealtimeNanos() - origin) / 1e9; }
    synchronized void mark(String name, String event) {
        phase = name;
        try {
            JSONObject marker = new JSONObject().put("type", "marker").put("elapsed_s", elapsed()).put("channel", name).put("event", event);
            if (markers.size() == 2000) { markers.removeFirst(); ++droppedMarkers; }
            markers.addLast(marker); journal(marker);
        }
        catch (Exception ignored) { }
    }
    private void journal(JSONObject row) {
        if (journal != null) try { journal.write(row.toString()); journal.newLine(); }
        catch (Exception e) { journalError = e.toString(); try { journal.close(); } catch (Exception ignored) { } journal = null; }
    }
    synchronized void beginChild(int pid) { childPid = pid; liveChildCpu = 0; memoryTime = -1; }
    synchronized void endChild(double cpuSeconds) {
        completedChildCpu += Math.max(liveChildCpu, Double.isFinite(cpuSeconds) ? Math.round(cpuSeconds * 1000) : 0);
        childPid = 0; liveChildCpu = 0; memoryTime = -1;
    }
    private Long childCpu() {
        if (childPid == 0) return 0L;
        if (clockTicks <= 0) return null;
        try (BufferedReader in = new BufferedReader(new FileReader("/proc/" + childPid + "/stat"))) {
            String line = in.readLine();
            String[] fields = line.substring(line.lastIndexOf(')') + 2).trim().split("\\s+");
            return (Long.parseLong(fields[11]) + Long.parseLong(fields[12])) * 1000 / clockTicks;
        } catch (Exception e) { return null; }
    }
    private static Long rssBytes(int pid) {
        try (BufferedReader in = new BufferedReader(new FileReader("/proc/" + (pid == 0 ? "self" : pid) + "/status"))) {
            String line;
            while ((line = in.readLine()) != null)
                if (line.startsWith("VmRSS:")) return Long.parseLong(line.substring(6).trim().split("\\s+")[0]) * 1024L;
        } catch (Exception ignored) { }
        return null;
    }
    private synchronized void sample() {
        final long begin = SystemClock.elapsedRealtimeNanos();
        try {
            final long now = SystemClock.elapsedRealtimeNanos(), appCpu = Process.getElapsedCpuTime();
            Long child = childCpu();
            if (child != null) liveChildCpu = Math.max(liveChildCpu, child);
            final long cpu = appCpu + completedChildCpu + liveChildCpu;
            JSONObject point = new JSONObject().put("type", "sample").put("elapsed_s", (now - origin) / 1e9)
                    .put("phase", phase).put("process_cpu_ms", cpu).put("app_cpu_ms", appCpu)
                    .put("native_child_cpu_ms", completedChildCpu + liveChildCpu).put("active_child_pid", childPid)
                    .put("cpu_counter_complete", child != null);
            double percent = child == null || lastTime < 0 || now <= lastTime || cpu < lastCpu ? Double.NaN
                    : (cpu - lastCpu) * 1e8 / (now - lastTime);
            point.put("cpu_one_core_pct", Double.isFinite(percent) ? percent : JSONObject.NULL);
            lastTime = child == null ? -1 : now; lastCpu = cpu;
            Long appRss = rssBytes(0), childRss = childPid == 0 ? 0L : rssBytes(childPid);
            point.put("rss_bytes", appRss == null || childRss == null ? JSONObject.NULL : appRss + childRss)
                    .put("app_rss_bytes", appRss == null ? JSONObject.NULL : appRss)
                    .put("child_rss_bytes", childRss == null ? JSONObject.NULL : childRss);
            // PSS walks memory mappings; keep this more expensive observation
            // to one per second and retain the age of cached values.
            if (memoryTime < 0 || now - memoryTime >= 1000000000L) {
                try {
                    Debug.MemoryInfo memory = new Debug.MemoryInfo();
                    Debug.getMemoryInfo(memory);
                    pss = memory.getTotalPss() * 1024L;
                    dirty = memory.getTotalPrivateDirty() * 1024L;
                    if (childPid != 0) {
                        Debug.MemoryInfo[] children = context.getSystemService(ActivityManager.class).getProcessMemoryInfo(new int[]{childPid});
                        if (children.length == 1 && children[0].getTotalPss() > 0) {
                            pss += children[0].getTotalPss() * 1024L;
                            dirty += children[0].getTotalPrivateDirty() * 1024L;
                        } else { pss = -1; dirty = -1; }
                    }
                    memoryTime = now;
                } catch (RuntimeException ignored) { pss = -1; dirty = -1; }
            }
            point.put("pss_bytes", pss < 0 ? JSONObject.NULL : pss)
                    .put("private_dirty_bytes", dirty < 0 ? JSONObject.NULL : dirty)
                    .put("pss_age_ms", memoryTime < 0 ? JSONObject.NULL : (now - memoryTime) / 1000000L);
            if (phoneMemoryTime < 0 || now - phoneMemoryTime >= 1000000000L) {
                try {
                    ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
                    context.getSystemService(ActivityManager.class).getMemoryInfo(memory);
                    phoneTotal = memory.totalMem; phoneAvailable = memory.availMem;
                    phoneThreshold = memory.threshold; phoneLowMemory = memory.lowMemory; phoneMemoryTime = now;
                } catch (RuntimeException e) { phoneTotal = phoneAvailable = phoneThreshold = -1; phoneLowMemory = null; }
            }
            point.put("system_memory_total_bytes", phoneTotal > 0 ? phoneTotal : JSONObject.NULL)
                    .put("system_memory_available_bytes", phoneAvailable >= 0 ? phoneAvailable : JSONObject.NULL)
                    .put("system_memory_threshold_bytes", phoneThreshold >= 0 ? phoneThreshold : JSONObject.NULL)
                    .put("system_low_memory", phoneLowMemory == null ? JSONObject.NULL : phoneLowMemory)
                    .put("system_memory_age_ms", phoneMemoryTime < 0 ? JSONObject.NULL : (now - phoneMemoryTime) / 1000000L)
                    .put("system_memory_available_pct", phoneTotal > 0 && phoneAvailable >= 0 ? 100.0 * phoneAvailable / phoneTotal : JSONObject.NULL);
            Long labMemory = pss >= 0 ? pss : appRss == null || childRss == null ? null : appRss + childRss;
            point.put("lab_memory_pct", phoneTotal > 0 && labMemory != null ? 100.0 * labMemory / phoneTotal : JSONObject.NULL)
                    .put("lab_memory_source", labMemory == null ? "unavailable" : pss >= 0 ? "pss" : "rss_estimate");
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
            journal(point);
            if (now - lastUi >= 1000000000L) {
                lastUi = now; if (journal != null) journal.flush(); changed.run();
            }
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
        synchronized (this) {
            if (journal != null) try { journal.close(); journal = null; } catch (Exception ignored) { }
        }
    }
    synchronized JSONObject snapshot() {
        try {
            JSONArray copy = new JSONArray();
            for (JSONObject sample : samples) copy.put(sample); // rows are immutable once published
            return new JSONObject().put("schema", 1).put("clock", "monotonic_wall_time")
                    .put("nominal_interval_ms", PERIOD_MS).put("memory_interval_ms", 1000)
                    .put("cpu_convention", "100 percent = one CPU core; app plus active native child, including sampler and UI")
                    .put("memory_scope", "sum of app and active native child; RSS can double-count shared pages, PSS is proportional")
                    .put("sampling_work_wall_ms", samplingWallMs).put("dropped_oldest_samples", dropped)
                    .put("samples", copy).put("markers", new JSONArray(markers))
                    .put("dropped_oldest_markers", droppedMarkers).put("journal_error", journalError)
                    .put("limits", new JSONArray().put("battery temperature is not CPU temperature")
                            .put("Android thermal severity is not a direct CPU temperature or frequency measurement")
                            .put("battery values are OS-reported and may update more slowly than sampling")
                            .put("sampled RSS/PSS may miss transient memory peaks; native lifetime RSS peak is recorded separately")
                            .put("sampling and chart work contribute to observed process CPU and memory"));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
}

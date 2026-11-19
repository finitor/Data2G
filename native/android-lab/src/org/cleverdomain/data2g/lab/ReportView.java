package org.cleverdomain.data2g.lab;

import android.content.Context;
import android.graphics.Color;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Locale;

/** Human-readable report and native graphs, including older schema-1 exports. */
final class ReportView extends LinearLayout {
    private final ArrayList<TimelineChart> charts = new ArrayList<>();
    private TextView sampling, memoryCaption;
    private TimelineChart memoryChart;
    private long phoneTotal;
    ReportView(Context context) { super(context); setOrientation(VERTICAL); }
    private TextView text(String s, boolean heading) {
        TextView v = new TextView(getContext());
        v.setText(s); v.setTextSize(heading ? 19 : 15); v.setTextColor(Color.rgb(28, 43, 54));
        int dp = (int)(getResources().getDisplayMetrics().density * 10);
        v.setPadding(0, dp, 0, dp); v.setTextIsSelectable(true); addView(v); return v;
    }
    void report(JSONObject r) {
        removeAllViews(); charts.clear();
        JSONArray trials = r.optJSONArray("trials");
        if (trials == null) throw new IllegalArgumentException("This JSON has no Data2G Lab trials.");
        sampling = memoryCaption = null; memoryChart = null; phoneTotal = 0;
        text("Results", true);
        if (r.has("planned_cases")) {
            text(r.optInt("completed_cases") + " / " + r.optInt("planned_cases") + " cases completed · " + r.optString("state"), true);
            text("Outcomes: " + r.optJSONObject("outcome_counts"), false);
            if (r.optBoolean("dashboard_recent_cases_only")) text("Showing the last three attempts. Browse all cases for the full archive. Resource graphs show the latest profiling segment; exports retain every segment and raw sample.", false);
        }
        JSONObject plan = r.optJSONObject("plan");
        if (plan != null) text("Pool threads: " + plan.optInt("effective_pool_threads") + (plan.optInt("requested_pool_threads") == 0 ? " (modem default)" : " (override)") + " · " + plan.optString("workload"), false);
        if (r.has("source_revision")) text("Native payload: " + r.optString("source_revision"), false);
        long started = r.optLong("started_utc_ms", 0);
        if (started > 0) text(DateFormat.getDateTimeInstance().format(new Date(started)), false);
        JSONObject device = r.optJSONObject("device_start");
        if (device != null) phoneTotal = device.optLong("memory_total_bytes");
        if (device != null) text(device.optString("manufacturer") + " " + device.optString("model") + " · Android " + device.optString("android"), false);
        if (trials.length() == 0) text("Run in progress. Graphs update while the test runs.", false);
        for (int i = 0; i < trials.length(); ++i) {
            JSONObject t = trials.optJSONObject(i);
            if (t == null) continue;
            String outcome = t.optString("outcome", "unknown");
            TextView title = text(t.optString("channel") + " · " + outcome.replace('_', ' '), true);
            title.setTextColor(outcome.equals("complete") ? Color.rgb(20, 105, 65) : Color.rgb(155, 66, 20));
            if (t.has("error")) { text(t.optString("error"), false); continue; }
            if (t.has("program")) {
                text(t.optString("program") + " · exit " + t.optInt("exit_code") + String.format(Locale.US, " · actual %.2f s", t.optDouble("wall_s", 0)), false);
                JSONObject summary = t.optJSONObject("native_summary");
                if (summary != null) {
                    if (summary.has("checks")) text(summary.optInt("checks") + " checks · " + summary.optInt("failures") + " failures", false);
                    text(String.format(Locale.US, "Child CPU %.2f s · Child peak RSS %.1f MiB", summary.optDouble("cpu_s", 0), summary.optDouble("peak_rss_bytes", 0) / 1048576), false);
                } else text("Native summary unavailable (for example, crash or forced cancellation). See the exit status and log.", false);
                text("Application goodput is not measured by this workload. Output:", false);
                JSONArray tail = t.optJSONArray("output_tail"); StringBuilder output = new StringBuilder();
                if (tail != null) for (int j = Math.max(0, tail.length() - 30); j < tail.length(); ++j) output.append(tail.optString(j)).append('\n');
                text(output.toString(), false); continue;
            }
            if (t.optString("workload_kind").equals("cpm_receiver_burst")) {
                text(t.optString("fixed_mode") + " · " + t.optDouble("snr_db") + " dB · seed " + t.optLong("seed"), false);
                text("Normal receiver: acquired " + t.optBoolean("acquired") + "; control " + t.optBoolean("base_control_ok") + "; data " + t.optBoolean("base_data_ok") + "\nSupplied timing/CFO/header diagnostic: control " + t.optBoolean("supplied_control_ok") + "; data " + t.optBoolean("supplied_data_ok"), false);
                text(String.format(Locale.US, "Normal / supplied processing: %.3f / %.3f s · Actual %.3f s · Process CPU %.3f s", t.optDouble("base_wall_s", 0), t.optDouble("supplied_wall_s", 0), t.optDouble("wall_s", 0), t.optDouble("process_cpu_s", 0)), false);
                text("A missed burst is a measured outcome. The supplied-information arm is a receiver diagnostic. Neither arm measures application goodput.", false); continue;
            }
            text(String.format(Locale.US, "Verified bytes: %d / %d\nSimulated: %.1f s · Actual: %.2f s\nProcess CPU: %.2f s · Lifetime peak RAM: %.1f MiB\n%s",
                    t.optInt("verified_at_a"), t.optInt("verified_at_b"), t.optDouble("simulated_s", 0), t.optDouble("wall_s", 0),
                    t.optDouble("process_cpu_s", 0), t.optDouble("process_lifetime_peak_rss_bytes", 0) / 1048576,
                    t.optString("clock_mode", "virtual_unpaced").equals("wall_clock_paced") ? "Wall-clock paced" : "Unpaced simulation"), false);
            text("Acknowledged: " + t.optBoolean("acknowledged") + " · Disconnected: " + t.optBoolean("disconnected"), false);
            if (t.has("delivered_average_bps")) text(String.format(Locale.US, "Whole-session delivered average (both directions): %.1f bit/s", t.optDouble("delivered_average_bps", 0)), false);
            JSONArray transfer = t.optJSONArray("transfer_trace");
            if (transfer != null) {
                text("Goodput · trailing 30 channel seconds", true);
                text("A→B and B→A count unique verified application bytes. ACK progress is separate. Warmup uses elapsed channel time; stalls decay to zero. These axes show simulated channel seconds, including setup and teardown, independently of the wall-time resource graphs.", false);
                try {
                    JSONObject series = new JSONObject().put("samples", transfer);
                    transferChart("Delivered bit/s", new String[]{"delivered_ab_bps", "delivered_ba_bps"}, series);
                    transferChart("Acknowledged bit/s", new String[]{"acked_ab_bps", "acked_ba_bps"}, series);
                } catch (Exception e) { text("Invalid transfer trace: " + e.getMessage(), false); }
            }
            JSONObject a = t.optJSONObject("a_engine_step"), b = t.optJSONObject("b_engine_step");
            if (a != null && b != null) text(String.format(Locale.US,
                    "Engine A work: %.2f s · p95/max %.1f/%.1f ms\nEngine B work: %.2f s · p95/max %.1f/%.1f ms\nChannel simulation: %.2f s",
                    a.optDouble("total_wall_s", 0), a.optDouble("p95_ms", 0), a.optDouble("max_ms", 0),
                    b.optDouble("total_wall_s", 0), b.optDouble("p95_ms", 0), b.optDouble("max_ms", 0), t.optDouble("channel_wall_s", 0)), false);
            if (t.optString("clock_mode").equals("wall_clock_paced"))
                text(String.format(Locale.US, "Pacing overruns: %d · Maximum lateness: %.1f ms", t.optInt("pacing_overruns"), t.optDouble("max_pacing_lateness_ms", 0)), false);
        }
        JSONObject profile = r.optJSONObject("profiling");
        if (profile == null) { text("This report has no timeline samples (an older build or profiling disabled). Enable profiling on a new run to collect graphs.", false); return; }
        text("Resource timelines", true);
        text("Horizontal axes show actual elapsed seconds. Tap a graph to inspect a sample. Vertical lines mark case starts. Measurements include this app and any active native test/tool child. Session runs include both modems and the channel. Unavailable counters appear as gaps.", false);
        sampling = text("", false);
        chart("CPU use · 100% = one CPU core", new String[]{"cpu_one_core_pct"}, new String[]{"App + child CPU"}, "%", 1, 100, false);
        text("Memory · share of phone RAM", true);
        memoryCaption = text("", false);
        memoryChart = new TimelineChart(getContext(), new String[]{"lab_memory_pct", "system_memory_available_pct"}, new String[]{"Lab (estimate)", "Available"}, "%", 1, 100, true);
        addView(memoryChart, new LayoutParams(LayoutParams.MATCH_PARENT, (int)(210 * getResources().getDisplayMetrics().density)));
        text("Both lines use the phone's total usable RAM as 100%. Higher available memory means more room for work. The lab estimate uses proportional memory (PSS) when Android provides it; otherwise resident memory (RSS), which can count shared pages twice. Available RAM includes memory Android can reclaim from caches.", false);
        chart("Battery temperature · °C", new String[]{"battery_temperature_c"}, new String[]{"Battery"}, "°C", 1, 0, false);
        text("Battery temperature is not CPU temperature. The OS may refresh this reading slowly.", false);
        chart("Android thermal severity · 0–6", new String[]{"thermal_status"}, new String[]{"Severity"}, "", 1, 6, true);
        text("0 none · 1 light · 2 moderate · 3 severe · 4 critical · 5 emergency · 6 shutdown. This is an OS severity signal, not a temperature sensor.", false);
        text("Paced simulations help measure duty cycle and heat, but do not qualify live-audio deadlines. Sampling and drawing contribute some overhead; short spikes between samples can be missed.", false);
        timeline(profile);
    }
    private void transferChart(String title, String[] keys, JSONObject series) {
        text(title, true);
        TimelineChart chart = new TimelineChart(getContext(), keys, new String[]{"A→B", "B→A"}, "bit/s", 1, 1, false).clock("simulated_s");
        addView(chart, new LayoutParams(LayoutParams.MATCH_PARENT, (int)(210 * getResources().getDisplayMetrics().density)));
        chart.data(series);
    }
    private void chart(String title, String[] keys, String[] names, String unit, double divisor, double top, boolean thermal) {
        text(title, true);
        TimelineChart chart = new TimelineChart(getContext(), keys, names, unit, divisor, top, thermal);
        addView(chart, new LayoutParams(LayoutParams.MATCH_PARENT, (int)(210 * getResources().getDisplayMetrics().density)));
        charts.add(chart);
    }
    void timeline(JSONObject profile) {
        JSONArray samples = profile.optJSONArray("samples");
        if (sampling != null) sampling.setText((samples == null ? 0 : samples.length()) + " samples · nominal 250 ms · PSS about once per second"
                + (profile.optInt("dropped_oldest_samples") > 0 ? " · oldest samples truncated" : ""));
        for (TimelineChart chart : charts) chart.data(profile);
        if (memoryChart != null) {
            try {
                JSONArray points = samples == null ? new JSONArray() : samples;
                JSONObject latest = points.length() == 0 ? new JSONObject() : points.getJSONObject(points.length() - 1);
                long total = latest.optLong("system_memory_total_bytes", phoneTotal);
                JSONObject plotted = profile;
                if (!latest.has("lab_memory_pct") && total > 0) {
                    JSONArray converted = new JSONArray();
                    for (int i = 0; i < points.length(); ++i) {
                        JSONObject source = points.getJSONObject(i);
                        double memory = source.optDouble("pss_bytes", source.optDouble("rss_bytes", Double.NaN));
                        converted.put(new JSONObject().put("elapsed_s", source.getDouble("elapsed_s")).put("lab_memory_pct", Double.isFinite(memory) ? 100 * memory / total : JSONObject.NULL));
                    }
                    plotted = new JSONObject().put("samples", converted).put("markers", profile.optJSONArray("markers"));
                }
                memoryChart.data(plotted);
                double lab = latest.optDouble("lab_memory_pct", Double.NaN);
                if (!Double.isFinite(lab) && total > 0) lab = 100 * latest.optDouble("pss_bytes", latest.optDouble("rss_bytes", Double.NaN)) / total;
                double available = latest.optDouble("system_memory_available_pct", Double.NaN);
                String caption = "Lab: " + (Double.isFinite(lab) ? String.format(Locale.US, "about %.0f%%", lab) : "unavailable")
                    + " · Available: " + (Double.isFinite(available) ? String.format(Locale.US, "%.0f%%", available) : "not recorded");
                if (total > 0) caption += String.format(Locale.US, "\nPhone usable RAM: %.2f GB", total / 1e9);
                if (latest.has("system_memory_available_bytes") && !latest.isNull("system_memory_available_bytes")) caption += String.format(Locale.US, " · available %.2f GB", latest.getDouble("system_memory_available_bytes") / 1e9);
                if (latest.has("system_memory_threshold_bytes") && !latest.isNull("system_memory_threshold_bytes")) caption += String.format(Locale.US, "\nAndroid low-memory threshold: %.0f MB", latest.getDouble("system_memory_threshold_bytes") / 1e6);
                if (latest.optBoolean("system_low_memory")) caption += " · Android reports low memory";
                memoryCaption.setText(caption);
            } catch (Exception e) { memoryCaption.setText("Memory context unavailable: " + e.getMessage()); }
        }
    }
}

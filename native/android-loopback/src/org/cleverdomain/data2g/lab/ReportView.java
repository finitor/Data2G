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
    private TextView sampling;
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
        text("Results", true);
        long started = r.optLong("started_utc_ms", 0);
        if (started > 0) text(DateFormat.getDateTimeInstance().format(new Date(started)), false);
        JSONObject device = r.optJSONObject("device_start");
        if (device != null) text(device.optString("manufacturer") + " " + device.optString("model") + " · Android " + device.optString("android"), false);
        if (trials.length() == 0) text("Run in progress. Graphs update while the test runs.", false);
        for (int i = 0; i < trials.length(); ++i) {
            JSONObject t = trials.optJSONObject(i);
            if (t == null) continue;
            String outcome = t.optString("outcome", "unknown");
            TextView title = text(t.optString("channel") + " · " + outcome.replace('_', ' '), true);
            title.setTextColor(outcome.equals("complete") ? Color.rgb(20, 105, 65) : Color.rgb(155, 66, 20));
            if (t.has("error")) { text(t.optString("error"), false); continue; }
            text(String.format(Locale.US, "Verified bytes: %d / %d\nSimulated: %.1f s · Actual: %.2f s\nProcess CPU: %.2f s · Lifetime peak RAM: %.1f MiB\n%s",
                    t.optInt("verified_at_a"), t.optInt("verified_at_b"), t.optDouble("simulated_s", 0), t.optDouble("wall_s", 0),
                    t.optDouble("process_cpu_s", 0), t.optDouble("process_lifetime_peak_rss_bytes", 0) / 1048576,
                    t.optString("clock_mode", "virtual_unpaced").equals("wall_clock_paced") ? "Wall-clock paced" : "Unpaced simulation"), false);
            text("Acknowledged: " + t.optBoolean("acknowledged") + " · Disconnected: " + t.optBoolean("disconnected"), false);
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
        text("Horizontal axes show actual elapsed seconds. Tap a graph to inspect a sample. Vertical lines mark case starts. All measurements include this app, both modems, the simulator and the profiler.", false);
        sampling = text("", false);
        chart("CPU use · 100% = one CPU core", new String[]{"cpu_one_core_pct"}, new String[]{"App CPU"}, "%", 1, 100, false);
        chart("App memory · MiB", new String[]{"rss_bytes", "pss_bytes"}, new String[]{"RSS", "PSS"}, "MiB", 1048576, 1, false);
        chart("Battery temperature · °C", new String[]{"battery_temperature_c"}, new String[]{"Battery"}, "°C", 1, 0, false);
        text("Battery temperature is not CPU temperature. The OS may refresh this reading slowly.", false);
        chart("Android thermal severity · 0–6", new String[]{"thermal_status"}, new String[]{"Severity"}, "", 1, 6, true);
        text("0 none · 1 light · 2 moderate · 3 severe · 4 critical · 5 emergency · 6 shutdown. This is an OS severity signal, not a temperature sensor.", false);
        text("Paced simulations help measure duty cycle and heat, but do not qualify live-audio deadlines. Sampling and drawing contribute some overhead; short spikes between samples can be missed.", false);
        timeline(profile);
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
    }
}

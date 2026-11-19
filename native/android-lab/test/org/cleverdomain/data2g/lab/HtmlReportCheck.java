package org.cleverdomain.data2g.lab;

import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.*;

/** Runs with Android's real org.json via app_process; no APK install or modem run. */
public final class HtmlReportCheck {
    private static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    private static byte[] bytes(InputStream in) throws Exception { try (InputStream source = in; ByteArrayOutputStream out = new ByteArrayOutputStream()) { byte[] b = new byte[32768]; int n; while ((n = source.read(b)) != -1) out.write(b, 0, n); return out.toByteArray(); } }
    private static String html(File zip) throws Exception { try (ZipFile z = new ZipFile(zip)) { return new String(bytes(z.getInputStream(z.getEntry("report.html"))), StandardCharsets.UTF_8); } }
    private static String data(String html, String id) { String tag = "<script type=\"application/json\" id=\"" + id + "\">"; int start = html.indexOf(tag); check(start >= 0, "data block " + id); start += tag.length(); return html.substring(start, html.indexOf("</script>", start)); }
    private static void export(File dir, File template, File zip) throws Exception { try (ZipOutputStream out = new ZipOutputStream(new FileOutputStream(zip))) { new RunStore(dir).export(out, new FileInputStream(template)); } }
    public static void main(String[] args) throws Exception {
        File actual = new File(args[0]), template = new File(args[1]), output = new File(args[2]), qa = new File(args[3]); qa.mkdirs();
        export(actual, template, output);
        String report = html(output); JSONArray cases = new JSONArray(data(report, "cases-data"));
        check(cases.length() == 26, "all 26 actual case summaries exported");
        check(new JSONArray(data(report, "previews-data")).length() == 3, "bounded detailed previews");
        check(new JSONArray(data(report, "segments-data")).length() == 1, "actual timeline exported");
        JSONObject profile = new JSONObject(data(report, "profile-0"));
        check(profile.getJSONArray("samples").length() == 650, "all actual preview samples exported");
        check(profile.getJSONArray("markers").toString().contains("test_pool"), "CPU spike retains suite markers");
        // Re-export an older archive without HTML. Preserve every raw entry.
        File old = new File(qa, "old.zip"), again = new File(qa, "again.zip");
        try (ZipFile original = new ZipFile(output); ZipOutputStream out = new ZipOutputStream(new FileOutputStream(old))) {
            Enumeration<? extends ZipEntry> entries = original.entries();
            while (entries.hasMoreElements()) { ZipEntry entry = entries.nextElement(); if (entry.getName().equals("report.html")) continue; out.putNextEntry(new ZipEntry(entry.getName())); out.write(bytes(original.getInputStream(entry))); out.closeEntry(); }
        }
        try (ZipOutputStream out = new ZipOutputStream(new FileOutputStream(again))) { HtmlReport.exportZip(old, new FileInputStream(template), out); }
        check(new JSONArray(data(html(again), "cases-data")).length() == 26, "old ZIP gains report");
        try (ZipFile a = new ZipFile(old); ZipFile b = new ZipFile(again)) {
            Enumeration<? extends ZipEntry> entries = a.entries();
            while (entries.hasMoreElements()) { ZipEntry e = entries.nextElement(); check(Arrays.equals(bytes(a.getInputStream(e)), bytes(b.getInputStream(b.getEntry(e.getName())))), "raw entry unchanged: " + e.getName()); }
        }
        File traversal = new File(qa, "bad.zip");
        try (ZipOutputStream out = new ZipOutputStream(new FileOutputStream(traversal))) { out.putNextEntry(new ZipEntry("../outside")); out.write(1); out.closeEntry(); }
        boolean rejected = false;
        try (ZipOutputStream out = new ZipOutputStream(new ByteArrayOutputStream())) { HtmlReport.exportZip(traversal, new FileInputStream(template), out); } catch (IOException expected) { rejected = true; }
        check(rejected, "unsafe archive path rejected");
        File fixture = new File(qa, "fixture"); fixture.mkdirs();
        RunStore synthetic = new RunStore(fixture, new JSONObject().put("first_case", 0).put("end_case", 125).put("workload", "export_fixture").put("source_revision", "fixture"), 1, 125);
        String attack = "</script><script>window.PWNED=true</script><img src=x onerror=alert(1)> & \u2028";
        for (int i = 0; i < 125; ++i) {
            JSONObject result = new JSONObject().put("workload_kind", i == 124 ? "two_endpoint_loopback" : "native_suite").put("outcome", i == 124 ? "complete" : "passed")
                    .put("channel", "nvis").put("fixed_mode", i == 124 ? attack : "").put("seed", i).put("wall_s", 1.2).put("process_cpu_s", .8);
            if (i < 124) result.put("program", "test_pool").put("native_summary", new JSONObject().put("checks", 13).put("failures", 0));
            else result.put("output_tail", new JSONArray().put(attack)).put("transfer_trace", new JSONArray()
                    .put(new JSONObject().put("simulated_s", 0).put("delivered_ab_bps", 0).put("delivered_ba_bps", 0).put("acked_ab_bps", 0).put("acked_ba_bps", 0))
                    .put(new JSONObject().put("simulated_s", 10).put("delivered_ab_bps", 80).put("delivered_ba_bps", 40).put("acked_ab_bps", 60).put("acked_ba_bps", 20)));
            synthetic.add(i, result);
        }
        synthetic.manifest.put("state", "finished").put("source_revision", "synthetic fixture").put("profiling_segment", 2).put("profiling_file", "resources-segment-2.json");
        JSONArray rows = new JSONArray();
        for (int i = 0; i < 5; ++i) rows.put(new JSONObject().put("elapsed_s", i * 2).put("cpu_one_core_pct", i == 2 ? 725 : i == 3 ? JSONObject.NULL : 100)
                .put("lab_memory_pct", 11).put("system_memory_available_pct", 47).put("battery_temperature_c", 28).put("thermal_status", 0));
        JSONObject timeline = new JSONObject().put("samples", rows).put("markers", new JSONArray().put(new JSONObject().put("elapsed_s", 0).put("event", "start").put("channel", "Case 18 · test_pool")));
        RunStore.write(new File(synthetic.directory, "resources-segment-1.json"), timeline.toString());
        RunStore.write(new File(synthetic.directory, "resources-segment-2.json"), timeline.toString());
        synthetic.checkpoint(synthetic.snapshot(), fixture, true);
        File syntheticZip = new File(qa, "fixture.zip"); export(synthetic.directory, template, syntheticZip);
        String syntheticHtml = html(syntheticZip);
        check(!syntheticHtml.contains(attack), "HTML script terminators escaped");
        JSONArray summaries = new JSONArray(data(syntheticHtml, "cases-data"));
        check(summaries.length() == 125 && summaries.getJSONObject(124).getString("fixed_mode").equals(attack), "all cases and literal strings round trip");
        check(new JSONArray(data(syntheticHtml, "segments-data")).length() == 2, "all resource segments embedded");
        File emptyParent = new File(qa, "empty"); emptyParent.mkdirs();
        RunStore empty = new RunStore(emptyParent, new JSONObject().put("first_case", 0), 1, 1); empty.checkpoint(empty.snapshot(), emptyParent, true);
        File emptyZip = new File(qa, "empty.zip"); export(empty.directory, template, emptyZip);
        check(new JSONArray(data(html(emptyZip), "cases-data")).length() == 0, "no-index empty run exports");
        System.out.println("PASS: actual 26-case report, resource samples/markers, raw ZIP preservation, old ZIP upgrade, safe paths, escaping, 125 cases, two segments and empty run");
    }
}

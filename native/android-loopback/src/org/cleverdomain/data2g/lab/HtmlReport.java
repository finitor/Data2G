package org.cleverdomain.data2g.lab;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.zip.*;

/** Streaming offline report exporter. It never loads the entire campaign into Java memory. */
final class HtmlReport {
    private interface Source {
        List<String> names() throws Exception;
        InputStream open(String name) throws Exception;
    }
    static void exportDirectory(File directory, JSONObject manifest, InputStream template, ZipOutputStream zip) throws Exception {
        final String metadata = manifest.toString();
        Source source = new Source() {
            public List<String> names() throws Exception { ArrayList<String> out = new ArrayList<>(); collect(directory, "", out); return out; }
            public InputStream open(String name) throws Exception {
                return name.equals("manifest.json") ? new ByteArrayInputStream(metadata.getBytes(StandardCharsets.UTF_8)) : new FileInputStream(new File(directory, name));
            }
        };
        export(source, template, zip);
    }
    static void exportZip(File archive, InputStream template, ZipOutputStream zip) throws Exception {
        try (ZipFile original = new ZipFile(archive)) {
            export(new Source() {
                public List<String> names() throws Exception {
                    ArrayList<String> out = new ArrayList<>(); HashSet<String> seen = new HashSet<>(); Enumeration<? extends ZipEntry> entries = original.entries();
                    while (entries.hasMoreElements()) {
                        ZipEntry e = entries.nextElement(); if (e.isDirectory()) continue;
                        if (!safePath(e.getName())) throw new IOException("Invalid archive path: " + e.getName());
                        if (!seen.add(e.getName())) throw new IOException("Duplicate archive entry: " + e.getName());
                        out.add(e.getName());
                    }
                    return out;
                }
                public InputStream open(String name) throws Exception {
                    ZipEntry e = original.getEntry(name); if (e == null) throw new FileNotFoundException(name);
                    return original.getInputStream(e);
                }
            }, template, zip);
        }
    }
    private static boolean safePath(String name) {
        if (name.isEmpty() || name.startsWith("/") || name.contains("\\")) return false;
        for (String part : name.split("/", -1)) if (part.equals("..") || part.equals(".") || part.isEmpty()) return false;
        return true;
    }
    private static void collect(File directory, String prefix, List<String> out) throws Exception {
        File[] files = directory.listFiles(); if (files == null) throw new IOException("Cannot list " + directory);
        for (File file : files) {
            if (Files.isSymbolicLink(file.toPath())) continue;
            if (file.isDirectory()) collect(file, prefix + file.getName() + "/", out);
            else if (file.isFile() && !file.getName().endsWith(".tmp")) out.add(prefix + file.getName());
        }
    }
    private static void export(Source source, InputStream template, ZipOutputStream zip) throws Exception {
        List<String> names = source.names();
        zip.putNextEntry(new ZipEntry("report.html"));
        Writer out = new BufferedWriter(new OutputStreamWriter(zip, StandardCharsets.UTF_8));
        String html;
        try (InputStream in = template) { html = read(in, 256 * 1024); }
        String marker = "<!-- REPORT_DATA -->";
        int position = html.indexOf(marker);
        if (position < 0 || html.indexOf(marker, position + marker.length()) >= 0) throw new IOException("Invalid HTML report template");
        out.write(html.substring(0, position));
        JSONObject manifest = json(source, "manifest.json");
        script(out, "manifest-data", manifest);
        script(out, "export-data", new JSONObject().put("html_schema", 1).put("exported_utc_ms", System.currentTimeMillis()));
        out.write("<script type=\"application/json\" id=\"cases-data\">[");
        ArrayDeque<JSONObject> previews = new ArrayDeque<>(); boolean first = true;
        Set<String> inventory = new HashSet<>(names);
        if (inventory.contains("index.jsonl")) {
            try (BufferedReader index = new BufferedReader(new InputStreamReader(source.open("index.jsonl"), StandardCharsets.UTF_8))) {
                String line;
                while ((line = index.readLine()) != null) {
                    JSONObject entry = new JSONObject(line); String path = entry.getString("file");
                    if (!path.matches("case-[0-9]+-attempt-[0-9]+\\.json")) throw new IOException("Invalid case path");
                    JSONObject result = json(source, path), summary = summary(result, path);
                    if (!first) out.write(','); first = false; safeJson(out, summary);
                    if (previews.size() == 3) previews.removeFirst();
                    previews.addLast(new JSONObject().put("file", path).put("result", result));
                }
            }
        }
        out.write("]</script>\n");
        script(out, "previews-data", new JSONArray(previews));
        ArrayList<String> resources = new ArrayList<>();
        for (String name : names) if (name.matches("resources-segment-[0-9]+\\.json")) resources.add(name);
        // Numeric segment ordering without overflowing on an imported file name.
        resources.sort(Comparator.comparingInt(String::length).thenComparing(Comparator.naturalOrder()));
        JSONArray segments = new JSONArray();
        JSONObject device = manifest.optJSONObject("device_start");
        long phoneTotal = device == null ? 0 : device.optLong("memory_total_bytes");
        for (int i = 0; i < resources.size(); ++i) {
            String file = resources.get(i), id = "profile-" + i;
            JSONObject profile = json(source, file);
            segments.put(new JSONObject().put("file", file).put("id", id));
            out.write("<script type=\"application/json\" id=\"" + id + "\">{\"samples\":[");
            JSONArray samples = profile.optJSONArray("samples");
            if (samples != null) for (int j = 0; j < samples.length(); ++j) {
                JSONObject row = samples.getJSONObject(j);
                long total = row.optLong("system_memory_total_bytes", phoneTotal);
                double lab = row.optDouble("lab_memory_pct", Double.NaN);
                if (!Double.isFinite(lab) && total > 0) lab = 100 * row.optDouble("pss_bytes", row.optDouble("rss_bytes", Double.NaN)) / total;
                JSONArray point = new JSONArray().put(number(row.optDouble("elapsed_s", Double.NaN)))
                        .put(number(row.optDouble("cpu_one_core_pct", Double.NaN))).put(number(lab))
                        .put(number(row.optDouble("system_memory_available_pct", Double.NaN)))
                        .put(number(row.optDouble("battery_temperature_c", Double.NaN)))
                        .put(number(row.optDouble("thermal_status", Double.NaN)));
                if (j != 0) out.write(','); safeJson(out, point);
            }
            out.write("],\"markers\":");
            safeJson(out, profile.optJSONArray("markers") == null ? new JSONArray() : profile.getJSONArray("markers"));
            out.write(",\"dropped_oldest_samples\":" + profile.optInt("dropped_oldest_samples") + "}</script>\n");
        }
        script(out, "segments-data", segments);
        out.write(html.substring(position + marker.length())); out.flush(); zip.closeEntry();
        byte[] buffer = new byte[32768];
        for (String name : names) {
            if (name.equals("report.html") || name.endsWith(".tmp")) continue;
            zip.putNextEntry(new ZipEntry(name));
            try (InputStream in = source.open(name)) { int n; while ((n = in.read(buffer)) != -1) zip.write(buffer, 0, n); }
            zip.closeEntry();
        }
    }
    private static Object number(double value) { return Double.isFinite(value) ? value : JSONObject.NULL; }
    private static JSONObject summary(JSONObject result, String path) throws Exception {
        JSONObject out = new JSONObject().put("file", path);
        for (String key : new String[]{"case_ordinal", "workload_kind", "program", "channel", "fixed_mode", "seed", "snr_db", "cfo_hz", "delay_ms", "doppler_2sigma_hz",
                "pool_threads", "requested_pool_threads", "default_pool_threads", "bytes_each_way", "clock_mode", "outcome", "error", "connected", "delivered", "acknowledged", "disconnected",
                "verified_at_a", "verified_at_b", "acknowledged_ab_bytes", "acknowledged_ba_bytes", "simulated_s", "wall_s", "process_cpu_s", "process_lifetime_peak_rss_bytes",
                "goodput_applicable", "goodput_clock", "goodput_window_s", "delivered_average_bps", "acquired", "base_control_ok", "base_data_ok", "supplied_control_ok", "supplied_data_ok",
                "base_wall_s", "supplied_wall_s", "exit_code", "native_summary"})
            if (result.has(key)) out.put(key, result.get(key));
        String log = result.optString("log_file"); int prefix = log.lastIndexOf("/program-");
        if (prefix >= 0 && log.substring(prefix + 1).matches("program-[0-9]+-[0-9]+/output\\.txt")) out.put("relative_log", log.substring(prefix + 1));
        return out;
    }
    private static JSONObject json(Source source, String name) throws Exception {
        try (InputStream in = source.open(name)) { return new JSONObject(read(in, 16 * 1024 * 1024)); }
    }
    private static String read(InputStream in, int limit) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int n;
        while ((n = in.read(buffer)) != -1) { if (out.size() + n > limit) throw new IOException("Report input exceeds limit"); out.write(buffer, 0, n); }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }
    private static void script(Writer out, String id, Object json) throws Exception {
        out.write("<script type=\"application/json\" id=\"" + id + "\">"); safeJson(out, json); out.write("</script>\n");
    }
    private static void safeJson(Writer out, Object json) throws Exception {
        // JSON data must never terminate its script element, including logs
        // containing literal </script>. Render all imported strings with textContent.
        out.write(json.toString().replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"));
    }
}

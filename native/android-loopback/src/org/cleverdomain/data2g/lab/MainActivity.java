package org.cleverdomain.data2g.lab;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Build;
import android.os.Debug;
import android.os.Bundle;
import android.os.PowerManager;
import android.os.SystemClock;
import android.text.InputType;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

/** Offline workload launcher, campaign archive and report viewer. */
public final class MainActivity extends Activity {
    static { System.loadLibrary("data2g_lab"); }
    private native void nativeReset();
    private native void nativeCancel();
    private native int nativeDefaultThreads();
    private native String nativeRevision();
    private native String nativeCpmModes();
    private native int nativeCampaignSize(String name, int trials);
    private native String nativeCampaignCase(String name, int ordinal, int trials, long seed);
    private native String nativeRun(String kind, String channel, String fixedMode, double snr, long seed,
                                  int bytes, int horizon, int threads, boolean paced, double cfo);
    private static final AtomicBoolean ENGINE_ACTIVE = new AtomicBoolean();
    private final String[] channels = {"clean", "awgn", "mpg", "mpp", "mpd", "mps", "flutter", "nvis", "hilat"};
    private final String[] workloads = {"custom", "quick", "hf_sessions", "hf_extreme", "cpm_floor", "native_all", "native_one", "listen", "replay", "burst"};
    private final String[] workloadNames = {"Selected loopback case", "Quick loopback suite", "Full HF session matrix", "Extreme HF session matrix", "Full CPM receiver campaign", "All 26 native suites", "Selected native suite", "Single receiver listening benchmark", "Single endpoint recording replay", "Recorded burst benchmark"};
    private Spinner workload, channel, mode, fixedMode, nativeSuite;
    private EditText snr, seed, bytes, horizon, threads, repeats, firstCase, caseLimit;
    private CheckBox profiling, automatic;
    private TextView status, live, fixtureLabel, activeCase;
    private Button run, stop, export, saved, open, resume, browse;
    private ScrollView formPage, reportPage;
    private ConsoleView console;
    private ReportView viewer;
    private JSONArray suiteCatalog = new JSONArray();
    private final ArrayList<String> availableSuites = new ArrayList<>();
    private volatile TimelineSampler sampler;
    private volatile boolean running, stopRequested, destroyed;
    private boolean fileBusy;
    private long lastTransferUi;
    private String lastJson = "";
    private File viewingDirectory, viewingZip, fixture;
    private String fixtureHash = "";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = column();
        label(root, "Data2G Android Lab · 4", 24);
        LinearLayout nav = new LinearLayout(this); root.addView(nav);
        button(nav, "Run", v -> page(false)); button(nav, "Results & graphs", v -> page(true)); button(nav, "Console", v -> consolePage());
        status = label(root, "Ready. Leaving the app cancels a running case; campaigns can resume.", 14);
        activeCase = label(root, "", 14);
        live = label(root, "", 14);
        FrameLayout pages = new FrameLayout(this); root.addView(pages, new LinearLayout.LayoutParams(-1, 0, 1));
        formPage = new ScrollView(this); LinearLayout form = column(); formPage.addView(form); pages.addView(formPage);
        label(form, "Workload", 18); workload = spinner(form, workloadNames);
        label(form, "Loopbacks measure two modems plus the channel. Replay and listening tools measure one endpoint. Native suites run their original checks in isolated processes.", 14);
        label(form, "Channel (selected case only)", 15); channel = spinner(form, channels);
        try {
            JSONArray modes = new JSONArray(nativeCpmModes()); String[] names = new String[modes.length() + 1]; names[0] = "Adaptive";
            for (int i = 0; i < modes.length(); ++i) names[i + 1] = modes.getString(i);
            label(form, "Mode (selected loopback case)", 15); fixedMode = spinner(form, names);
            try (InputStream in = getAssets().open("native-suites.json")) { suiteCatalog = new JSONObject(read(in)).getJSONArray("suites"); }
            for (int i = 0; i < suiteCatalog.length(); ++i) if (suiteCatalog.getJSONObject(i).getBoolean("available")) availableSuites.add(suiteCatalog.getJSONObject(i).getString("id"));
        } catch (Exception e) { status.setText("Native catalog error: " + e.getMessage()); }
        label(form, "Native suite", 15); nativeSuite = spinner(form, availableSuites.toArray(new String[0]));
        button(form, "View suite coverage and exclusions", v -> {
            StringBuilder text = new StringBuilder();
            for (int i = 0; i < suiteCatalog.length(); ++i) { JSONObject item = suiteCatalog.optJSONObject(i); text.append(item.optString("id")).append(item.optBoolean("available") ? ": included" : ": " + item.optString("reason")).append('\n'); }
            new AlertDialog.Builder(this).setTitle("Native coverage").setMessage(text.toString()).setPositiveButton("Close", null).show();
        });
        mode = spinner(form, new String[]{"Wall-clock paced loopbacks", "Unpaced loopbacks"});
        label(form, "Pacing applies to sessions. Native tests, burst diagnostics and existing replay/benchmark tools run at their own speed. Live audio deadlines are not qualified by pacing.", 14);
        snr = field(form, "SNR in 2500 Hz, dB (selected case)", "12", true);
        seed = field(form, "First seed", "1", false);
        bytes = field(form, "Application bytes each direction (sessions)", "64", false);
        horizon = field(form, "Session horizon / replay or listening seconds (1–600)", "180", false);
        automatic = new CheckBox(this); automatic.setText("Use modem default (" + nativeDefaultThreads() + " pool threads on this phone)"); automatic.setChecked(true); form.addView(automatic);
        threads = field(form, "Pool thread override (1–32)", String.valueOf(nativeDefaultThreads()), false); threads.setEnabled(false);
        automatic.setOnCheckedChangeListener((v, checked) -> threads.setEnabled(!checked));
        label(form, "Some original suites intentionally change their own pool size. FFT threads are managed separately by the core.", 14);
        repeats = field(form, "Seeds per HF grid point / repetitions (1–1000)", "1", false);
        label(form, "HF sessions: adaptive + six fixed CPM modes, 8 SNR points, 8 channels. Extreme: NVIS and high latitude. CPM: all 558 public grid points; 100 seeds gives 55,800 cases. Paired normal receiver and supplied timing/CFO/header diagnostic; other Python research arms are excluded.", 14);
        firstCase = field(form, "First case index (0 = beginning)", "0", false);
        caseLimit = field(form, "Case limit (0 = all remaining cases)", "0", false);
        profiling = new CheckBox(this); profiling.setText("Record CPU, memory and thermal timelines"); profiling.setChecked(true); form.addView(profiling);
        fixtureLabel = label(form, "No recording selected", 14);
        button(form, "Import recording (.f16) or burst (.d2gb)", v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), 3));
        button(form, "Preview case count", v -> { try { JSONObject p = configuration(); status.setText(planDescription(p)); } catch (Exception e) { status.setText(e.getMessage()); } });
        run = button(form, "Run workload", v -> { try { launch(configuration(), null); } catch (Exception e) { status.setText(e.getMessage()); } });
        stop = button(root, "Cancel run", v -> { stopRequested = true; nativeCancel(); }); stop.setVisibility(View.GONE);
        reportPage = new ScrollView(this); LinearLayout reports = column(); reportPage.addView(reports); pages.addView(reportPage);
        saved = button(reports, "Open saved run", v -> openSaved());
        open = button(reports, "Open JSON or campaign ZIP from Files", v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), 2));
        resume = button(reports, "Resume this campaign", v -> {
            try { if (viewingDirectory == null) throw new IllegalArgumentException("Open a local campaign first."); RunStore store = new RunStore(viewingDirectory); launch(store.manifest.getJSONObject("plan"), store); }
            catch (Exception e) { status.setText(e.getMessage()); }
        });
        browse = button(reports, "Browse all cases", v -> browseCases(0));
        export = button(reports, "Export report / complete campaign ZIP", v -> {
            boolean archive = viewingDirectory != null || viewingZip != null;
            startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).setType(archive ? "application/zip" : "application/json").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE, archive ? "data2g-lab-campaign.zip" : "data2g-lab-results.json"), 1);
        });
        viewer = new ReportView(this); reports.addView(viewer); console = new ConsoleView(this); pages.addView(console); setContentView(root); page(false); enabled(true);
        File latest = new File(getExternalFilesDir(null), "latest.json");
        if (latest.isFile()) try { JSONObject r = new JSONObject(RunStore.read(latest)); File candidate = new File(r.optString("local_case_directory", "")); if (ownDirectory(candidate)) loadLocal(candidate); else display(r.toString()); } catch (Exception e) { status.setText("Restore: " + e.getMessage()); }
        Intent intent = getIntent();
        if (Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null) try (InputStream in = getContentResolver().openInputStream(intent.getData())) { viewingDirectory = viewingZip = null; display(read(in)); page(true); } catch (Exception e) { status.setText(e.getMessage()); }
        if ("results".equals(intent.getStringExtra("page"))) page(true);
        if ("console".equals(intent.getStringExtra("page"))) consolePage();
        if (intent.getBooleanExtra("auto", false)) {
            select(workload, workloads, intent.getStringExtra("workload")); if (intent.getBooleanExtra("suite", false)) workload.setSelection(1);
            select(channel, channels, intent.getStringExtra("channel"));
            snr.setText(intent.getStringExtra("snr") == null ? "12" : intent.getStringExtra("snr"));
            seed.setText(String.valueOf(intent.getLongExtra("seed", 1))); bytes.setText(String.valueOf(intent.getIntExtra("bytes", 64)));
            horizon.setText(String.valueOf(intent.getIntExtra("horizon", 180))); repeats.setText(String.valueOf(intent.getIntExtra("repeats", 1)));
            firstCase.setText(String.valueOf(intent.getIntExtra("first", 0))); caseLimit.setText(String.valueOf(intent.getIntExtra("limit", 0)));
            int pool = intent.getIntExtra("threads", 0); automatic.setChecked(pool == 0); if (pool != 0) threads.setText(String.valueOf(pool));
            mode.setSelection(intent.getBooleanExtra("paced", true) ? 0 : 1); profiling.setChecked(intent.getBooleanExtra("profiling", true));
            String requestedSuite = intent.getStringExtra("native_suite"); if (requestedSuite != null && availableSuites.contains(requestedSuite)) nativeSuite.setSelection(availableSuites.indexOf(requestedSuite));
            String requestedMode = intent.getStringExtra("fixed_mode");
            for (int i = 1; i < fixedMode.getCount(); ++i) if (fixedMode.getItemAtPosition(i).equals(requestedMode)) fixedMode.setSelection(i);
            String input = intent.getStringExtra("fixture");
            if (input != null) try { File f = new File(input); if (!ownFile(f) || f.length() > 256L * 1024 * 1024) throw new IOException("Invalid local fixture"); fixture = f; fixtureHash = hash(f); fixtureLabel.setText(f.getName() + " · SHA256 " + fixtureHash.substring(0, 12)); }
            catch (Exception e) { status.setText(e.getMessage()); return; }
            root.post(() -> { try { if (intent.getBooleanExtra("resume", false) && viewingDirectory != null) { RunStore prior = new RunStore(viewingDirectory); launch(prior.manifest.getJSONObject("plan"), prior); } else launch(configuration(), null); } catch (Exception e) { status.setText(e.toString()); } });
        }
    }
    private void select(Spinner spinner, String[] values, String value) { for (int i = 0; i < values.length; ++i) if (values[i].equals(value)) spinner.setSelection(i); }
    private LinearLayout column() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); int pad = (int)(12 * getResources().getDisplayMetrics().density); v.setPadding(pad, pad, pad, pad); return v; }
    private void page(boolean reports) { console.setVisibility(View.GONE); formPage.setVisibility(reports ? View.GONE : View.VISIBLE); reportPage.setVisibility(reports ? View.VISIBLE : View.GONE); }
    private void consolePage() { formPage.setVisibility(View.GONE); reportPage.setVisibility(View.GONE); console.setVisibility(View.VISIBLE); }
    private TextView label(LinearLayout parent, String text, int size) { TextView v = new TextView(this); v.setText(text); v.setTextSize(size); parent.addView(v); return v; }
    private Spinner spinner(LinearLayout parent, String[] values) { Spinner v = new Spinner(this); v.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item, values)); parent.addView(v); return v; }
    private EditText field(LinearLayout parent, String name, String value, boolean signed) { label(parent, name, 15); EditText v = new EditText(this); v.setInputType(InputType.TYPE_CLASS_NUMBER | (signed ? InputType.TYPE_NUMBER_FLAG_SIGNED | InputType.TYPE_NUMBER_FLAG_DECIMAL : 0)); v.setSingleLine(true); v.setText(value); parent.addView(v); return v; }
    private Button button(LinearLayout parent, String name, View.OnClickListener action) { Button b = new Button(this); b.setText(name); b.setOnClickListener(action); parent.addView(b); return b; }
    public void progress(String text) { if (!destroyed) console.append(text); }
    public void transferProgress(String json) {
        long now = SystemClock.elapsedRealtime(); if (now - lastTransferUi < 500) return; lastTransferUi = now;
        try { JSONObject p = new JSONObject(json); final String text = String.format(Locale.US, "Last 30 channel seconds · delivered A→B %.1f / B→A %.1f bit/s\nACK progress A→B %.1f / B→A %.1f bit/s", p.getDouble("delivered_ab_bps"), p.getDouble("delivered_ba_bps"), p.getDouble("acked_ab_bps"), p.getDouble("acked_ba_bps")); runOnUiThread(() -> { if (!destroyed) live.setText(text); }); } catch (Exception ignored) { }
    }
    private JSONObject device() throws Exception { ActivityManager.MemoryInfo m = new ActivityManager.MemoryInfo(); getSystemService(ActivityManager.class).getMemoryInfo(m); Debug.MemoryInfo p = new Debug.MemoryInfo(); Debug.getMemoryInfo(p); return new JSONObject().put("manufacturer", Build.MANUFACTURER).put("model", Build.MODEL).put("android", Build.VERSION.RELEASE).put("api", Build.VERSION.SDK_INT).put("abis", new JSONArray(Build.SUPPORTED_ABIS)).put("memory_total_bytes", m.totalMem).put("memory_available_bytes", m.availMem).put("app_pss_bytes", p.getTotalPss() * 1024L).put("thermal_status", getSystemService(PowerManager.class).getCurrentThermalStatus()); }
    private void enabled(boolean ready) { ready = ready && !fileBusy; run.setEnabled(ready); open.setEnabled(ready); saved.setEnabled(ready); export.setEnabled(ready && !lastJson.isEmpty()); resume.setEnabled(ready && viewingDirectory != null); browse.setEnabled(ready && (viewingDirectory != null || viewingZip != null)); stop.setVisibility(running ? View.VISIBLE : View.GONE); }
    private int number(EditText field) { return Integer.parseInt(field.getText().toString()); }
    private JSONObject configuration() throws Exception {
        double db = Double.parseDouble(snr.getText().toString()); long initialSeed = Long.parseLong(seed.getText().toString());
        int n = number(bytes), seconds = number(horizon), pool = automatic.isChecked() ? 0 : number(threads), repetitions = number(repeats), first = number(firstCase), limit = number(caseLimit);
        if (!Double.isFinite(db) || db < -30 || db > 60 || initialSeed < 0 || initialSeed > Long.MAX_VALUE - 1000 || n < 1 || n > 65536 || seconds < 1 || seconds > 600 || pool < 0 || pool > 32 || (!automatic.isChecked() && pool == 0) || repetitions < 1 || repetitions > 1000 || first < 0 || limit < 0) throw new IllegalArgumentException("Check settings: SNR -30..60, bytes 1..65536, seconds 1..600, override 1..32, seeds 1..1000.");
        String type = workloads[workload.getSelectedItemPosition()];
        int total = type.startsWith("hf_") || type.equals("cpm_floor") ? nativeCampaignSize(type, repetitions) : repetitions * (type.equals("native_all") ? availableSuites.size() : type.equals("quick") ? 3 : 1);
        if (first >= total) throw new IllegalArgumentException("First case must be below " + total);
        JSONObject p = new JSONObject().put("workload", type).put("source_revision", nativeRevision()).put("channel", channels[channel.getSelectedItemPosition()]).put("fixed_mode", fixedMode.getSelectedItemPosition() == 0 ? "" : fixedMode.getSelectedItem().toString()).put("snr_db", db).put("seed", initialSeed).put("bytes", n).put("horizon", seconds).put("requested_pool_threads", pool).put("effective_pool_threads", pool == 0 ? nativeDefaultThreads() : pool).put("repetitions", repetitions).put("paced", mode.getSelectedItemPosition() == 0).put("profiling", profiling.isChecked()).put("first_case", first).put("end_case", limit == 0 ? total : (int)Math.min(total, (long)first + limit)).put("full_plan_cases", total).put("native_suites", new JSONArray(availableSuites)).put("native_suite", nativeSuite.getSelectedItem());
        if (type.equals("replay") || type.equals("burst")) { if (fixture == null || !fixture.isFile() || (type.equals("replay") != fixture.getName().equals("audio_in.f16"))) throw new IllegalArgumentException("Import the appropriate recording first."); p.put("fixture", fixture.getAbsolutePath()).put("fixture_sha256", fixtureHash); }
        return p;
    }
    private String channelDescription(String name) {
        switch (name) {
        case "mpg": return "MPG · 0.5 ms / 0.1 Hz Doppler";
        case "mpp": return "MPP · 2 ms / 1 Hz Doppler";
        case "mpd": return "MPD · 4 ms / 2 Hz Doppler";
        case "mps": return "MPS (empirical) · 2 ms / 0.15 Hz Doppler";
        case "flutter": return "Flutter · 0.5 ms / 10 Hz Doppler";
        case "nvis": return "NVIS · 7 ms / 1 Hz Doppler";
        case "hilat": return "High latitude · 7 ms / 30 Hz Doppler";
        default: return name;
        }
    }
    private String planDescription(JSONObject p) { return (p.optInt("end_case") - p.optInt("first_case")) + " cases selected out of " + p.optInt("full_plan_cases") + " · pool " + p.optInt("effective_pool_threads") + (p.optInt("requested_pool_threads") == 0 ? " (automatic)" : " (override)"); }
    private JSONObject caseAt(JSONObject p, int ordinal) throws Exception {
        String type = p.getString("workload"); int repetitions = p.getInt("repetitions");
        if (type.startsWith("hf_") || type.equals("cpm_floor")) return new JSONObject(nativeCampaignCase(type, ordinal, repetitions, p.getLong("seed")));
        JSONObject c = new JSONObject().put("workload_kind", "two_endpoint_loopback").put("channel", p.getString("channel")).put("fixed_mode", p.getString("fixed_mode")).put("snr_db", p.getDouble("snr_db")).put("seed", p.getLong("seed") + (type.equals("quick") ? ordinal / 3 : ordinal)).put("cfo_hz", 0);
        if (type.equals("quick")) c.put("channel", new String[]{"clean", "awgn", "mpp"}[ordinal % 3]);
        if (type.startsWith("native_")) c.put("workload_kind", "native_suite").put("program", type.equals("native_all") ? p.getJSONArray("native_suites").getString(ordinal % p.getJSONArray("native_suites").length()) : p.getString("native_suite"));
        if (type.equals("listen") || type.equals("replay") || type.equals("burst")) {
            JSONArray args = new JSONArray(); int pool = p.getInt("effective_pool_threads");
            if (type.equals("replay")) args.put(new File(p.getString("fixture")).getParent()).put("--seconds").put(String.valueOf(p.getInt("horizon"))).put("--threads").put(String.valueOf(pool)).put("--call").put("LAB1").put("--worker");
            else { args.put("--threads").put(String.valueOf(pool)); if (type.equals("listen")) args.put("--listen").put(String.valueOf(p.getInt("horizon"))); else args.put("--reps").put("1").put(p.getString("fixture")); }
            c.put("workload_kind", type.equals("replay") ? "single_endpoint_replay" : "receiver_benchmark").put("program", type.equals("replay") ? "data2g-replay" : "data2g-bench-rx").put("args", args);
        }
        return c;
    }
    private void launch(JSONObject plan, RunStore prior) throws Exception {
        if (running || fileBusy) return;
        if (!nativeRevision().equals(plan.getString("source_revision"))) throw new IllegalArgumentException("Native payload changed. Start a new run to keep results tied to one build.");
        if (plan.has("fixture")) { File input = new File(plan.getString("fixture")); if (!ownFile(input) || !plan.getString("fixture_sha256").equals(hash(input))) throw new IllegalArgumentException("Recording changed or missing; import it and start a new run."); }
        int first = prior == null ? plan.getInt("first_case") : prior.manifest.getInt("next_case"), end = plan.getInt("end_case");
        if (first >= end) throw new IllegalArgumentException("This campaign is already complete.");
        if (!ENGINE_ACTIVE.compareAndSet(false, true)) throw new IllegalStateException("Previous run is stopping; try again shortly.");
        final RunStore store;
        try { store = prior == null ? new RunStore(getExternalFilesDir(null), plan, System.currentTimeMillis(), end - first) : prior; }
        catch (Exception e) { ENGINE_ACTIVE.set(false); throw e; }
        running = true; stopRequested = false; nativeReset(); lastTransferUi = 0;
        viewingDirectory = store.directory; viewingZip = null; enabled(false); live.setText(""); console.reset(); status.setText(planDescription(plan)); consolePage();
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        new Thread(() -> {
            TimelineSampler monitor = null; boolean failed = false;
            try {
                if (prior == null && plan.has("fixture")) {
                    File source = new File(plan.getString("fixture")), folder = new File(store.directory, "input");
                    if (!folder.mkdirs()) throw new IOException("Cannot retain input recording");
                    File retained = new File(folder, source.getName());
                    try (InputStream in = new FileInputStream(source); OutputStream out = new FileOutputStream(retained)) { copy(in, out, 256L * 1024 * 1024); }
                    plan.put("fixture", retained.getAbsolutePath());
                }
                store.manifest.put("source_revision", nativeRevision()).put("device_start", prior == null ? device() : store.manifest.get("device_start")).put("resource_scope", "app_plus_active_native_child").put("profiling_segment", store.manifest.optInt("profiling_segment") + 1).put("state", "running");
                if (plan.getBoolean("profiling")) {
                    monitor = new TimelineSampler(this, () -> runOnUiThread(() -> { TimelineSampler s = sampler; if (!destroyed && s != null && reportPage.getVisibility() == View.VISIBLE) viewer.timeline(s.snapshot()); }), new File(store.directory, "resources-segment-" + store.manifest.getInt("profiling_segment") + ".jsonl"));
                    sampler = monitor; monitor.start();
                }
                checkpoint(store, monitor, true); long lastSave = SystemClock.elapsedRealtime();
                for (int ordinal = first; ordinal < end && !stopRequested; ++ordinal) {
                    JSONObject c = caseAt(plan, ordinal); String name = "Case " + (ordinal + 1) + "/" + end + " · " + c.optString("workload_kind");
                    if (c.has("program")) name += " · " + c.getString("program");
                    else name += "\nMode: " + (c.optString("fixed_mode").isEmpty() ? "adaptive" : c.getString("fixed_mode")) + " · " + channelDescription(c.getString("channel")) + "\nSNR " + c.getDouble("snr_db") + " dB / 2500 Hz · seed " + c.getLong("seed") + " · CFO " + c.getDouble("cfo_hz") + " Hz";
                    final String heading = name;
                    runOnUiThread(() -> { if (!destroyed) { activeCase.setText(heading); live.setText(""); } });
                    progress(name); if (monitor != null) monitor.mark(name, "start");
                    JSONObject result;
                    try {
                        if (c.has("program")) result = NativeProgram.run(this, c, new File(store.directory, "program-" + ordinal + "-" + (store.manifest.optInt("attempted_cases") + 1)), plan.getInt("effective_pool_threads"), monitor, () -> stopRequested, this::progress);
                        else result = new JSONObject(nativeRun(c.getString("workload_kind"), c.getString("channel"), c.optString("fixed_mode"), c.getDouble("snr_db"), c.getLong("seed"), plan.getInt("bytes"), plan.getInt("horizon"), plan.getInt("requested_pool_threads"), c.getString("workload_kind").equals("two_endpoint_loopback") && plan.getBoolean("paced"), c.getDouble("cfo_hz")));
                    } catch (Exception e) { result = new JSONObject(c.toString()).put("outcome", stopRequested ? "cancelled" : "runtime_error").put("error", e.toString()); }
                    store.add(ordinal, result); progress("Result: " + result.optString("outcome") + (result.has("base_data_ok") ? " · normal data=" + result.optBoolean("base_data_ok") + " · supplied data=" + result.optBoolean("supplied_data_ok") : "")); if (monitor != null) monitor.mark(name, "end");
                    if (SystemClock.elapsedRealtime() - lastSave >= 1000 || result.optString("outcome").equals("cancelled")) { checkpoint(store, monitor, false); lastSave = SystemClock.elapsedRealtime(); }
                    if (result.optString("outcome").equals("cancelled")) break;
                }
            } catch (Exception e) { failed = true; try { store.manifest.put("error", e.toString()); } catch (Exception ignored) { } }
            finally {
                try { if (monitor != null) monitor.finish(); store.manifest.put("state", failed ? "error" : stopRequested ? "cancelled" : "finished").put("device_latest", device()); checkpoint(store, monitor, true); }
                catch (Exception e) { failed = true; progress("Save failed: " + e.getMessage()); }
                sampler = null; running = false; ENGINE_ACTIVE.set(false); final boolean error = failed;
                runOnUiThread(() -> { if (!destroyed) { enabled(true); getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); console.append("Run ended: " + (error ? "error" : stopRequested ? "cancelled" : "finished")); status.setText(error ? "Run error. See partial report." : stopRequested ? "Cancelled. Results saved; resume retries the interrupted case." : "Finished. All cases and graphs saved."); } });
            }
        }, "data2g-lab").start();
    }
    private void checkpoint(RunStore store, TimelineSampler monitor, boolean force) throws Exception { JSONObject report = store.snapshot(); if (monitor != null) report.put("profiling", monitor.snapshot()); store.checkpoint(report, getExternalFilesDir(null), force); final String text = report.toString(); runOnUiThread(() -> { if (!destroyed) try { display(text); } catch (Exception e) { status.setText(e.getMessage()); } }); }
    private void display(String json) throws Exception {
        JSONObject report = new JSONObject(json); JSONArray trials = report.optJSONArray("trials"); if (trials == null || trials.length() > 10000) throw new IllegalArgumentException("Not a supported Lab report");
        JSONObject profile = report.optJSONObject("profiling"); if (profile != null) { JSONArray samples = profile.optJSONArray("samples"); if (samples != null) { if (samples.length() > 12000) throw new IllegalArgumentException("Too many samples"); double previous = -1; for (int i = 0; i < samples.length(); ++i) { double t = samples.getJSONObject(i).optDouble("elapsed_s", Double.NaN); if (!Double.isFinite(t) || t < previous || t < 0) throw new IllegalArgumentException("Invalid timestamps"); previous = t; } } }
        viewer.report(report); lastJson = report.toString(); enabled(!running);
    }
    private boolean ownFile(File file) throws Exception { File root = getExternalFilesDir(null); return root != null && file.getCanonicalPath().startsWith(root.getCanonicalPath() + File.separator) && file.isFile(); }
    private boolean ownDirectory(File file) throws Exception { File root = getExternalFilesDir(null); return root != null && root.getCanonicalFile().equals(file.getCanonicalFile().getParentFile()) && file.getName().startsWith("campaign-") && new File(file, "manifest.json").isFile(); }
    private void loadLocal(File dir) throws Exception { if (!ownDirectory(dir)) throw new IllegalArgumentException("Invalid local campaign"); JSONObject report = new JSONObject(RunStore.read(new File(dir, "manifest.json"))); String name = report.optString("profiling_file"); if (name.matches("resources-segment-[0-9]+\\.json") && new File(dir, name).isFile()) report.put("profiling", new JSONObject(RunStore.read(new File(dir, name)))); viewingDirectory = dir; viewingZip = null; display(report.toString()); page(true); }
    private static String read(InputStream in) throws Exception { if (in == null) throw new IllegalArgumentException("Cannot open file"); ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buf = new byte[8192]; int n; while ((n = in.read(buf)) != -1) { if (out.size() + n > 16 * 1024 * 1024) throw new IllegalArgumentException("JSON exceeds 16 MiB"); out.write(buf, 0, n); } return new String(out.toByteArray(), StandardCharsets.UTF_8); }
    private void openSaved() {
        File[] files = getExternalFilesDir(null).listFiles((d, n) -> n.startsWith("campaign-") || n.startsWith("run-") && n.endsWith(".json")); if (files == null || files.length == 0) { status.setText("No saved runs"); return; }
        Arrays.sort(files, Comparator.comparing(File::getName).reversed()); String[] names = new String[files.length]; for (int i = 0; i < files.length; ++i) names[i] = files[i].getName();
        new AlertDialog.Builder(this).setTitle("Saved runs").setItems(names, (dialog, index) -> { try { if (files[index].isDirectory()) loadLocal(files[index]); else { viewingDirectory = viewingZip = null; display(RunStore.read(files[index])); page(true); } } catch (Exception e) { status.setText(e.getMessage()); } }).show();
    }
    private InputStream caseInput(String name) throws Exception { if (!name.matches("index\\.jsonl|case-[0-9]+-attempt-[0-9]+\\.json")) throw new IllegalArgumentException("Invalid case path"); if (viewingDirectory != null) return new FileInputStream(new File(viewingDirectory, name)); ZipFile zip = new ZipFile(viewingZip); try { InputStream in = zip.getInputStream(zip.getEntry(name)); return new FilterInputStream(in) { @Override public void close() throws IOException { super.close(); zip.close(); } }; } catch (Exception e) { zip.close(); throw e; } }
    private void browseCases(int offset) {
        try {
            ArrayList<JSONObject> rows = new ArrayList<>(); boolean more;
            try (BufferedReader in = new BufferedReader(new InputStreamReader(caseInput("index.jsonl"), StandardCharsets.UTF_8))) { String line; for (int i = 0; i < offset; ++i) if (in.readLine() == null) break; for (int i = 0; i < 200 && (line = in.readLine()) != null; ++i) rows.add(new JSONObject(line)); more = in.readLine() != null; }
            ArrayList<String> names = new ArrayList<>(); for (JSONObject row : rows) names.add("#" + row.optInt("ordinal") + " " + row.optString("channel") + " " + row.optString("fixed_mode") + " " + row.optDouble("snr_db") + " dB · " + row.optString("outcome")); if (more) names.add("Next 200 cases…");
            new AlertDialog.Builder(this).setTitle("Cases " + offset + " onward").setItems(names.toArray(new String[0]), (dialog, which) -> { if (which == rows.size()) browseCases(offset + 200); else try (InputStream in = caseInput(rows.get(which).getString("file"))) { JSONObject trial = new JSONObject(read(in)); JSONObject r = new JSONObject().put("trials", new JSONArray().put(trial)); display(r.toString()); page(true); } catch (Exception e) { status.setText(e.getMessage()); } }).setNegativeButton("Close", null).show();
        } catch (Exception e) { status.setText("Case browser: " + e.getMessage()); }
    }
    private static String hash(File f) throws Exception { MessageDigest d = MessageDigest.getInstance("SHA-256"); try (InputStream in = new FileInputStream(f)) { byte[] b = new byte[32768]; int n; while ((n = in.read(b)) != -1) d.update(b, 0, n); } StringBuilder s = new StringBuilder(); for (byte b : d.digest()) s.append(String.format(Locale.US, "%02x", b & 255)); return s.toString(); }
    private static void copy(InputStream in, OutputStream out, long limit) throws Exception { if (in == null || out == null) throw new IOException("Cannot open file"); byte[] b = new byte[32768]; long size = 0; int n; while ((n = in.read(b)) != -1) { size += n; if (size > limit) throw new IOException("File exceeds " + limit + " bytes"); out.write(b, 0, n); } }
    private void importFixture(InputStream in) throws Exception {
        File dir = new File(getExternalFilesDir(null), "fixtures/" + System.currentTimeMillis()); if (!dir.mkdirs()) throw new IOException("Cannot create fixture directory"); File raw = new File(dir, "input");
        try (OutputStream out = new FileOutputStream(raw)) { copy(in, out, 256L * 1024 * 1024); }
        boolean burst = false;
        try (FileInputStream source = new FileInputStream(raw)) { byte[] head = new byte[36]; int read = source.read(head); burst = read >= 4 && head[0] == 'D' && head[1] == '2' && head[2] == 'G' && head[3] == 'B'; if (burst) { if (read != 36) throw new IOException("Truncated burst header"); ByteBuffer b = ByteBuffer.wrap(head).order(ByteOrder.LITTLE_ENDIAN); long samples = b.getLong(4); int cw = b.getInt(20), payload = b.getInt(24); if (samples <= 0 || samples > 32L * 1024 * 1024 || cw < 1 || cw > 256 || payload < 1 || payload > 65536 || 36 + samples * 8 + (long)cw * payload > raw.length()) throw new IOException("Invalid burst lengths"); } else if (raw.length() < 2 || raw.length() % 2 != 0) throw new IOException("Expected little-endian float16 mono 8 kHz recording"); }
        File target = new File(dir, burst ? "burst.d2gb" : "audio_in.f16"); if (!raw.renameTo(target)) throw new IOException("Cannot retain recording"); fixture = target; fixtureHash = hash(target); final String description = target.getName() + " · " + target.length() + " bytes · SHA256 " + fixtureHash.substring(0, 12); runOnUiThread(() -> fixtureLabel.setText(description));
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data); if (result != RESULT_OK || data == null || data.getData() == null) return;
        fileBusy = true; enabled(false); status.setText("Reading / writing file…");
        final File local = viewingDirectory, archive = viewingZip; final String reportText = lastJson;
        new Thread(() -> {
            try {
                if (request == 1) {
                    try (OutputStream out = getContentResolver().openOutputStream(data.getData())) {
                        if (out == null) throw new IOException("Cannot open export");
                        if (local != null) try (ZipOutputStream zip = new ZipOutputStream(out); InputStream template = getAssets().open("report.html")) { new RunStore(local).export(zip, template); }
                        else if (archive != null) try (ZipOutputStream zip = new ZipOutputStream(out); InputStream template = getAssets().open("report.html")) { HtmlReport.exportZip(archive, template, zip); }
                        else out.write(reportText.getBytes(StandardCharsets.UTF_8));
                    }
                    runOnUiThread(() -> status.setText("Exported."));
                } else if (request == 3) { try (InputStream in = getContentResolver().openInputStream(data.getData())) { importFixture(in); } runOnUiThread(() -> status.setText("Recording imported.")); }
                else if (request == 2) {
                    File imported = new File(getCacheDir(), "imported-report");
                    try (InputStream in = getContentResolver().openInputStream(data.getData()); OutputStream out = new FileOutputStream(imported)) { copy(in, out, 1024L * 1024 * 1024); }
                    byte[] magic = new byte[2]; try (InputStream in = new FileInputStream(imported)) { in.read(magic); }
                    boolean zipped = magic[0] == 'P' && magic[1] == 'K'; final String text;
                    if (zipped) try (ZipFile zip = new ZipFile(imported)) {
                        JSONObject report = new JSONObject(read(zip.getInputStream(zip.getEntry("manifest.json"))));
                        String name = report.optString("profiling_file");
                        if (name.matches("resources-segment-[0-9]+\\.json") && zip.getEntry(name) != null) report.put("profiling", new JSONObject(read(zip.getInputStream(zip.getEntry(name)))));
                        text = report.toString();
                    } else text = RunStore.read(imported);
                    runOnUiThread(() -> { try { viewingDirectory = null; viewingZip = zipped ? imported : null; display(text); page(true); status.setText("Viewing imported report."); } catch (Exception e) { status.setText(e.getMessage()); } });
                }
            } catch (Exception e) { runOnUiThread(() -> status.setText("File error: " + e.getMessage())); }
            finally { runOnUiThread(() -> { fileBusy = false; if (!destroyed) enabled(!running); }); }
        }, "lab-files").start();
    }
    @Override protected void onStop() { if (running) { stopRequested = true; nativeCancel(); } super.onStop(); }
    @Override protected void onDestroy() { destroyed = true; if (running) { stopRequested = true; nativeCancel(); } super.onDestroy(); }
}

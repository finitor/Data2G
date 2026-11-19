package org.cleverdomain.data2g.lab;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.view.MotionEvent;
import android.view.View;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.Locale;

/** Small native plot; no WebView, script engine, network or chart dependency. */
final class TimelineChart extends View {
    private static final int[] COLORS = {Color.rgb(20, 105, 170), Color.rgb(186, 83, 20)};
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final String[] keys, names;
    private final String unit;
    private final double divisor, minimumTop;
    private final boolean thermal;
    private String timeKey = "elapsed_s";
    private JSONArray points = new JSONArray(), markers = new JSONArray();
    private int selected = -1;
    private final float dp;

    TimelineChart(Context context, String[] keys, String[] names, String unit, double divisor, double minimumTop, boolean thermal) {
        super(context);
        this.keys = keys; this.names = names; this.unit = unit; this.divisor = divisor;
        this.minimumTop = minimumTop; this.thermal = thermal;
        dp = getResources().getDisplayMetrics().density;
        setMinimumHeight((int)(200 * dp));
        setContentDescription(String.join(", ", names) + " timeline. Tap to inspect a sample.");
    }
    TimelineChart clock(String key) { timeKey = key; return this; }
    void data(JSONObject profile) {
        points = profile.optJSONArray("samples");
        if (points == null) points = new JSONArray();
        markers = profile.optJSONArray("markers");
        if (markers == null) markers = new JSONArray();
        selected = Math.min(selected, points.length() - 1);
        invalidate();
    }
    @Override protected void onDraw(Canvas c) {
        super.onDraw(c);
        float left = 54 * dp, right = getWidth() - 12 * dp, top = 28 * dp, bottom = getHeight() - (keys.length > 1 ? 58 : 44) * dp;
        paint.setTypeface(android.graphics.Typeface.DEFAULT);
        paint.setTextSize(11 * dp); paint.setStrokeWidth(dp);
        double first = points.length() == 0 ? 0 : points.optJSONObject(0).optDouble(timeKey, 0);
        double last = points.length() == 0 ? 1 : points.optJSONObject(points.length() - 1).optDouble(timeKey, 1);
        double end = Math.max(first + .25, last), low = 0, high = minimumTop;
        boolean hasValue = false;
        for (int i = 0; i < points.length(); ++i)
            for (String key : keys) {
                double v = points.optJSONObject(i).optDouble(key, Double.NaN) / divisor;
                if (Double.isFinite(v)) { high = Math.max(high, v); hasValue = true; }
            }
        if (unit.equals("°C") && hasValue) {
            low = Double.POSITIVE_INFINITY;
            for (int i = 0; i < points.length(); ++i) {
                double v = points.optJSONObject(i).optDouble(keys[0], Double.NaN);
                if (Double.isFinite(v)) low = Math.min(low, v);
            }
            low = Math.floor(low - 1); high = Math.ceil(high + 1);
        } else if (!thermal) high = Math.max(minimumTop, Math.ceil(high * 1.1));
        if (high <= low) high = low + 1;
        for (int i = 0; i <= 3; ++i) {
            float y = top + (bottom - top) * i / 3;
            paint.setColor(Color.rgb(222, 229, 234)); c.drawLine(left, y, right, y, paint);
            paint.setColor(Color.DKGRAY);
            c.drawText(String.format(Locale.US, "%.0f", high - (high - low) * i / 3), 4 * dp, y + 4 * dp, paint);
        }
        float previousMarkerLabel = -100 * dp;
        for (int i = 0; i < markers.length(); ++i) {
            JSONObject marker = markers.optJSONObject(i);
            if (marker == null || !marker.optString("event").equals("start")) continue;
            double t = marker.optDouble("elapsed_s", -1);
            if (t < first || t > end) continue;
            float x = left + (float)((t - first) / (end - first)) * (right - left);
            paint.setColor(Color.LTGRAY); c.drawLine(x, top, x, bottom, paint);
            if (x - previousMarkerLabel > 65 * dp) {
                paint.setColor(Color.GRAY); c.drawText(marker.optString("channel"), x + 2 * dp, top - 7 * dp, paint);
                previousMarkerLabel = x;
            }
        }
        for (int k = 0; k < keys.length; ++k) {
            Path path = new Path(); boolean connected = false;
            paint.setColor(COLORS[k % COLORS.length]); paint.setStrokeWidth(2 * dp);
            for (int i = 0; i < points.length(); ++i) {
                JSONObject p = points.optJSONObject(i);
                double t = p.optDouble(timeKey, Double.NaN), v = p.optDouble(keys[k], Double.NaN) / divisor;
                if (!Double.isFinite(t) || !Double.isFinite(v)) { connected = false; continue; }
                float x = left + (float)((t - first) / (end - first)) * (right - left);
                float y = bottom - (float)((v - low) / (high - low)) * (bottom - top);
                if (!connected) path.moveTo(x, y); else path.lineTo(x, y);
                c.drawCircle(x, y, 1.8f * dp, paint); connected = true;
            }
            paint.setStyle(Paint.Style.STROKE); c.drawPath(path, paint); paint.setStyle(Paint.Style.FILL);
        }
        paint.setColor(Color.DKGRAY);
        c.drawText(String.format(Locale.US, "%.1f s", first), left, bottom + 16 * dp, paint);
        c.drawText(String.format(Locale.US, "%.1f s", last), Math.max(left, right - 42 * dp), bottom + 16 * dp, paint);
        int index = selected >= 0 ? selected : points.length() - 1;
        for (int k = 0; k < keys.length; ++k) {
            double v = index >= 0 ? points.optJSONObject(index).optDouble(keys[k], Double.NaN) / divisor : Double.NaN;
            String value = names[k] + ": " + (Double.isFinite(v) ? String.format(Locale.US, "%.1f %s", v, unit) : "unavailable");
            paint.setColor(COLORS[k % COLORS.length]);
            c.drawText(value, left, getHeight() - (8 + 14 * (keys.length - k - 1)) * dp, paint);
        }
        if (selected >= 0 && selected < points.length()) {
            double t = points.optJSONObject(selected).optDouble(timeKey, first);
            float x = left + (float)((t - first) / (end - first)) * (right - left);
            paint.setColor(Color.GRAY); paint.setStrokeWidth(dp); c.drawLine(x, top, x, bottom, paint);
            c.drawText(String.format(Locale.US, "At %.2f s", t), left, 12 * dp, paint);
        }
    }
    @Override public boolean onTouchEvent(MotionEvent event) {
        if (points.length() == 0) return false;
        if (event.getAction() == MotionEvent.ACTION_DOWN || event.getAction() == MotionEvent.ACTION_MOVE) {
            double first = points.optJSONObject(0).optDouble(timeKey, 0);
            double last = points.optJSONObject(points.length() - 1).optDouble(timeKey, first);
            double fraction = Math.max(0, Math.min(1, (event.getX() - 54 * dp) / Math.max(1, getWidth() - 66 * dp)));
            double target = first + fraction * (last - first), best = Double.POSITIVE_INFINITY;
            for (int i = 0; i < points.length(); ++i) {
                double distance = Math.abs(points.optJSONObject(i).optDouble(timeKey, first) - target);
                if (distance < best) { best = distance; selected = i; }
            }
            invalidate(); return true;
        }
        if (event.getAction() == MotionEvent.ACTION_UP) { performClick(); return true; }
        return true;
    }
    @Override public boolean performClick() { super.performClick(); return true; }
}

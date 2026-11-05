package in.liftbook.app;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.view.View;
import android.widget.RemoteViews;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Liftbook's home-screen widget. The app works out what it shows (Liftbook.widgetSummary in
 * web/app/data.js) for each of the next days and hands it over through WidgetBridgePlugin; this
 * only picks today's and draws it. Tapping the widget opens that session's targets in the app,
 * the "+ Log" button opens Log.
 */
public class LiftbookWidget extends AppWidgetProvider {
    static final String PREFS = "liftbook_widget";
    static final String KEY = "days";
    private static final int[] LINES = { R.id.widget_line1, R.id.widget_line2, R.id.widget_line3, R.id.widget_line4 };

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) manager.updateAppWidget(id, draw(context));
    }

    /** Redraws every Liftbook widget on the home screen (after the app saved new summaries). */
    static void refreshAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, LiftbookWidget.class));
        if (ids.length > 0) manager.updateAppWidget(ids, draw(context));
    }

    /** Today's summary: {"heading","title","lines":[{"name","aim"}],"more","route"}, or null. */
    static JSONObject today(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        try {
            JSONObject days = new JSONObject(prefs.getString(KEY, "{}"));
            String key = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
            return days.optJSONObject(key);
        } catch (Exception e) {
            return null;
        }
    }

    static RemoteViews draw(Context context) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_liftbook);
        JSONObject day = today(context);
        String route = "";
        if (day == null) {
            views.setTextViewText(R.id.widget_heading, "Liftbook");
            views.setTextViewText(R.id.widget_title, context.getString(R.string.widget_open_app));
            for (int line : LINES) views.setViewVisibility(line, View.GONE);
            views.setViewVisibility(R.id.widget_more, View.GONE);
        } else {
            route = day.optString("route", "");
            views.setTextViewText(R.id.widget_heading, day.optString("heading", "Next"));
            views.setTextViewText(R.id.widget_title, day.optString("title", "Workout"));
            JSONArray lines = day.optJSONArray("lines");
            for (int i = 0; i < LINES.length; i++) {
                JSONObject line = lines != null ? lines.optJSONObject(i) : null;
                if (line == null) {
                    views.setViewVisibility(LINES[i], View.GONE);
                } else {
                    views.setTextViewText(LINES[i], line.optString("name", "") + "  ·  " + line.optString("aim", ""));
                    views.setViewVisibility(LINES[i], View.VISIBLE);
                }
            }
            int more = day.optInt("more", 0);
            views.setTextViewText(R.id.widget_more, "+ " + more + " more");
            views.setViewVisibility(R.id.widget_more, more > 0 ? View.VISIBLE : View.GONE);
        }
        views.setOnClickPendingIntent(R.id.widget_root, open(context, route, 1));
        views.setOnClickPendingIntent(R.id.widget_log, open(context, "log", 2));
        return views;
    }

    /** Opens the app on a page: in.liftbook.app://open#/<route> (see onLink in web/app/main.js). */
    private static PendingIntent open(Context context, String route, int requestCode) {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse("in.liftbook.app://open#/" + route));
        intent.setPackage(context.getPackageName());
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(context, requestCode, intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
}

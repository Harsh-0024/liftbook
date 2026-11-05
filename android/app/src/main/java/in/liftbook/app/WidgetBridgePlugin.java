package in.liftbook.app;

import android.content.Context;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * The web app's way to the home-screen widget (window.Capacitor.Plugins.LiftbookWidget):
 * update({ days: { "YYYY-MM-DD": summary, ... } }) keeps the summaries on the phone, where the
 * widget reads them even when the app is closed, and redraws the widget now.
 */
@CapacitorPlugin(name = "LiftbookWidget")
public class WidgetBridgePlugin extends Plugin {
    @PluginMethod
    public void update(PluginCall call) {
        JSObject days = call.getObject("days", new JSObject());
        Context context = getContext();
        context.getSharedPreferences(LiftbookWidget.PREFS, Context.MODE_PRIVATE)
            .edit().putString(LiftbookWidget.KEY, days.toString()).apply();
        LiftbookWidget.refreshAll(context);
        call.resolve();
    }

    /** Signed out: the widget goes back to "Open Liftbook once to fill this in". */
    @PluginMethod
    public void clear(PluginCall call) {
        Context context = getContext();
        context.getSharedPreferences(LiftbookWidget.PREFS, Context.MODE_PRIVATE).edit().remove(LiftbookWidget.KEY).apply();
        LiftbookWidget.refreshAll(context);
        call.resolve();
    }
}

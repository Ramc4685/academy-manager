package com.courtmastr.academy;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Without google-services.json, PushNotifications.register() throws inside
        // the bridge and kills the app. The web app only registers when this
        // marker plugin is present (frontend/lib/auth/native-push.ts).
        if (getResources().getIdentifier("google_app_id", "string", getPackageName()) != 0) {
            registerPlugin(PushReadyPlugin.class);
        }
        super.onCreate(savedInstanceState);
    }
}

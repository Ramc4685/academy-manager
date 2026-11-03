package com.courtmastr.academy;

import com.getcapacitor.Plugin;
import com.getcapacitor.annotation.CapacitorPlugin;

/** Marker: registered only when Firebase is configured, so push can register safely. */
@CapacitorPlugin(name = "PushReady")
public class PushReadyPlugin extends Plugin {}

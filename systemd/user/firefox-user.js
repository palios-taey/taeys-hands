// Taey consultation profile settings
// Prevents tab contamination — only one tab per consultation.

// Disable session restore — no reopening previous tabs on startup
user_pref("browser.startup.page", 0);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.sessionstore.resume_session_once", false);
user_pref("browser.sessionstore.max_tabs_undo", 0);
user_pref("browser.sessionstore.max_windows_undo", 0);

// No homepage multi-URL expansion
user_pref("browser.startup.homepage_override.mstone", "ignore");

// Don't warn when closing multiple tabs (there should only be one anyway)
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.warnOnCloseOtherTabs", false);

// Disable "What's new" page and other auto-opens
user_pref("browser.startup.homepage_override.buildID", "");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("startup.homepage_override_url", "");

// Disable extension updates that might open tabs
user_pref("extensions.update.autoUpdateDefault", false);

// Disable telemetry prompts
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("datareporting.policy.firstRunURL", "");

// Disable crash reporter UI
user_pref("browser.tabs.crashReporting.email", "");
user_pref("browser.crashReports.unsubmittedCheck.autoSubmit2", false);

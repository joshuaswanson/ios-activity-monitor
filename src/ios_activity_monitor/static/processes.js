// Plain-English descriptions of common iOS daemons and processes.
// `desc` is the explanation. `hot` is what it usually means when CPU is high.

window.IOS_PROCESSES = {
  // ─── app installation / management ───
  installd: {
    desc: "Installs, updates, and removes apps. After an iOS update or iCloud restore, it re-validates every app's signature and re-prebinds it against the new system libraries.",
    hot: "Almost always means a recent iOS update or restore is still finishing — leave it plugged in for an hour or two.",
  },
  lsd: {
    desc: "Launch Services daemon. Maintains the catalog of apps, file types, and URL handlers so iOS knows which app opens what.",
    hot: "Usually correlates with installd activity — app catalog being rebuilt.",
  },
  pkd: {
    desc: "PlugInKit daemon. Manages app extensions like share sheets, widgets, Siri intents, and keyboards.",
  },
  runningboardd: {
    desc: "Tracks every running process — when apps are launched, suspended, or terminated. The iOS equivalent of a job control system.",
  },
  mobile_installation_proxy: {
    desc: "Lets Xcode and similar tools install apps over the cable.",
  },
  mobile_image_mounter: {
    desc: "Mounts the Developer Disk Image when you connect the phone to Xcode or pymobiledevice3.",
  },
  lockdownd: {
    desc: "Top-level device management service. Anything on the Mac talking to the iPhone over USB goes through lockdownd first.",
  },

  // ─── UI ───
  SpringBoard: {
    desc: "The iOS home screen, lock screen, and app switcher. Effectively the iOS desktop environment.",
    hot: "Usually means lots of animations, notifications, or UI redraws (e.g. lock screen widgets refreshing).",
  },
  backboardd: {
    desc: "The lower-level UI server. Handles touch input, the display pipeline, sensors, and hardware buttons.",
    hot: "Often elevated when the screen is on, scrolling, or many apps are animating in the background.",
  },
  Preferences: {
    desc: "The Settings app.",
  },

  // ─── photos / files / indexing ───
  fseventsd: {
    desc: "Watches the filesystem for changes so Spotlight, iCloud, Photos and others can react.",
    hot: "Usually triggered by Spotlight reindexing after an iOS update, after a large file import, or by photo library scanning.",
  },
  mds: {
    desc: "Spotlight metadata daemon — extracts and indexes text from files.",
    hot: "Reindexing in progress. Will finish on its own once the phone has been idle on power for a while.",
  },
  mds_stores: {
    desc: "Worker process for Spotlight indexing.",
    hot: "Same as mds — reindexing.",
  },
  photoanalysisd: {
    desc: "Runs ML on your photo library: face recognition, scene detection, building Memories.",
    hot: "Photo analysis runs in long batches when the phone is on power and idle. Common after a backup restore or a big import.",
  },
  mediaanalysisd: {
    desc: "Runs ML on photos and videos: text recognition (Live Text), object detection.",
    hot: "Same as photoanalysisd — runs in batches when idle.",
  },
  photolibraryd: {
    desc: "Manages the Photos library database.",
  },
  assetsd: {
    desc: "Photos asset store — actual photo and video files.",
  },
  mobileassetd: {
    desc: "Downloads on-demand system assets: dictionaries, Siri voices, fonts, font subsets, language models.",
    hot: "Often spikes after an iOS update as it backfills assets in the background.",
  },
  bird: {
    desc: "iCloud Drive file provider. Syncs files between the device and iCloud.",
    hot: "Lots of files changed or downloading.",
  },
  cloudd: {
    desc: "Top-level iCloud sync coordinator (CloudKit).",
    hot: "Big sync in progress — usually self-resolves.",
  },
  cloudphotod: {
    desc: "Syncs Photos with iCloud Photo Library.",
    hot: "Uploading new photos to iCloud, or downloading thumbnails after a fresh sign-in.",
  },
  nsurlsessiond: {
    desc: "Background URL session downloader. Apps use it to download large files (Music, Podcasts, App Store, iCloud).",
    hot: "A large download is in progress.",
  },

  // ─── push / sync / scheduling ───
  apsd: {
    desc: "Apple Push Notification Service client. Maintains the long-lived connection that delivers push notifications.",
  },
  dasd: {
    desc: "Duet Activity Scheduler. The background-task scheduler — picks when to run things like backups, indexing, and ML.",
    hot: "Brief spikes are normal. Sustained spikes usually mean a misbehaving app's background activity.",
  },
  duetexpertd: {
    desc: "On-device intelligence — powers Siri Suggestions, Shortcuts predictions, proactive widgets.",
    hot: "Routine after big behavior changes (new apps, recent restore) as it rebuilds suggestions.",
  },
  knowledge_agent: {
    desc: "Stores anonymous on-device usage knowledge for Siri Suggestions and Screen Time.",
  },
  suggestd: {
    desc: "Mines emails and messages for contacts, events, and addresses to suggest.",
  },
  routined: {
    desc: "Tracks significant locations (frequent locations, work, home) for Maps, Photos, and Siri.",
  },
  searchpartyd: {
    desc: "Find My network — both for locating this device and helping locate others.",
  },

  // ─── media / audio ───
  mediaserverd: {
    desc: "The audio and video pipeline — playback, capture, mixing, system sounds.",
    hot: "Audio or video playback is active, or a screen recording.",
  },
  audiomxd: {
    desc: "Audio mixer daemon — routes audio between apps, hardware, and Bluetooth.",
  },
  mediaplaybackd: {
    desc: "Powers playback for Music, Podcasts, and Audiobooks.",
  },
  mediaremoted: {
    desc: "Coordinates Now Playing — Control Center music widget, lock-screen controls, AirPlay handoff.",
  },
  avconferenced: {
    desc: "FaceTime audio/video conferencing engine.",
  },

  // ─── communication ───
  CommCenter: {
    desc: "Cellular radio coordinator. Handles voice, SMS, and data over the cellular network.",
  },
  imagent: {
    desc: "iMessage agent — sending, receiving, and syncing iMessages.",
  },
  identityservicesd: {
    desc: "Identity for iMessage, FaceTime, and Continuity. Looks up which of your contacts are reachable.",
  },
  callservicesd: {
    desc: "Routes incoming and outgoing phone calls, including CallKit and VoIP.",
  },
  sharingd: {
    desc: "AirDrop, Handoff, Universal Clipboard, AirPlay discovery.",
  },
  rapportd: {
    desc: "Peer-to-peer discovery layer for Continuity, Handoff, AirDrop.",
  },
  chronod: {
    desc: "Syncs data with a paired Apple Watch.",
  },

  // ─── radios / connectivity ───
  bluetoothd: {
    desc: "Bluetooth radio control and pairing.",
  },
  wifid: {
    desc: "Wi-Fi radio control and scanning.",
  },
  WirelessRadioManagerd: {
    desc: "Coordinates the cellular and Wi-Fi radios.",
  },
  locationd: {
    desc: "Location Services — provides GPS, Wi-Fi, and cellular-based location to apps.",
    hot: "An app is using location actively (Maps, weather, fitness).",
  },

  // ─── security / identity ───
  securityd: {
    desc: "The security daemon. Manages the keychain, trust evaluation, and cryptographic operations.",
  },
  trustd: {
    desc: "Evaluates SSL/TLS certificate trust for the whole system.",
  },
  akd: {
    desc: "Apple ID account daemon — token refresh, two-factor auth, sign-in.",
  },
  accountsd: {
    desc: "Internet Accounts — the central store for mail, calendar, contacts, and other configured accounts.",
  },
  CloudKeychainProxy: {
    desc: "Syncs the iCloud Keychain (passwords, passkeys) across your devices.",
  },
  passd: {
    desc: "Apple Wallet — passes, transit cards, payment cards.",
  },

  // ─── health / sensors ───
  healthd: {
    desc: "Health database — heart rate, steps, sleep, etc.",
  },
  biomed: {
    desc: "Biometric sensor service.",
  },

  // ─── home / siri ───
  homed: {
    desc: "HomeKit daemon — controls smart-home accessories.",
  },
  assistantd: {
    desc: "Siri — speech recognition, intent matching, on-device understanding.",
  },
  siriknowledged: {
    desc: "On-device Siri knowledge base.",
  },

  // ─── system core ───
  launchd: {
    desc: "The first userspace process. Launches and supervises every other system process.",
    hot: "Genuinely rare. Usually means many short-lived processes are being spawned.",
  },
  kernel_task: {
    desc: "The kernel itself, plus kernel extensions. Often used as a thermal-management proxy — when the chip gets hot, iOS parks workload here to throttle.",
    hot: "High kernel_task often means the phone is throttling because it's hot. Cool the phone down (remove case, take out of direct sun).",
  },
  UserEventAgent: {
    desc: "Dispatches system events to interested daemons.",
  },
  logd: {
    desc: "Unified logging daemon — collects log messages from all processes.",
  },
  diagnosticd: {
    desc: "Diagnostics collection.",
  },
  analyticsd: {
    desc: "Diagnostics & Usage data collection (only enabled if you opted in).",
  },
  aggregated: {
    desc: "Aggregates anonymous on-device usage statistics.",
  },
  distnoted: {
    desc: "Distributed notifications — cross-process pub/sub messaging.",
  },
  notifyd: {
    desc: "Low-level notification dispatch (NOT push notifications; that's apsd).",
  },
  mobilegestaltd: {
    desc: "Reports hardware info (model, serial, capabilities) to other processes.",
  },
  containermanagerd: {
    desc: "Manages the per-app data containers (sandboxes).",
  },

  // ─── apps (capitalized names) ───
  Photos: {
    desc: "The Photos app foreground process.",
  },
  Messages: {
    desc: "The Messages app foreground process.",
  },
  Safari: {
    desc: "The Safari app foreground process.",
  },
  Mail: {
    desc: "The Mail app foreground process.",
  },
  Maps: {
    desc: "The Maps app foreground process.",
  },
  Music: {
    desc: "The Music app foreground process.",
  },
  MobileSMS: {
    desc: "The Messages app (older internal name).",
  },
  MobileSafari: {
    desc: "Safari (older internal name).",
  },
  MobileMail: {
    desc: "Mail (older internal name).",
  },

  // ─── developer / our own ───
  DTServiceHub: {
    desc: "Developer Tools service hub. This is the service Xcode/pymobiledevice3 use to query process data. Yes, this is us.",
    hot: "Expected — it's the process collecting the data you're looking at right now.",
  },
  sysmond: {
    desc: "The system monitor daemon — the iOS service that's actually producing this process list.",
    hot: "Expected — it's the process producing this data.",
  },
  remotepairingdeviced: {
    desc: "Manages the developer tunnel between the iPhone and a paired Mac.",
    hot: "Expected — this is the service maintaining the connection over which we're streaming data.",
  },
  dtfetchsymbolsd: {
    desc: "Fetches symbol files for developer tools.",
  },

  // ─── other commonly seen ───
  swcd: {
    desc: "Shared Web Credentials — Universal Links, password autofill across web and apps.",
  },
  navigationd: {
    desc: "Maps turn-by-turn navigation engine.",
  },
  weatherd: {
    desc: "Weather data daemon — provides forecasts to the Weather app and widgets.",
  },
  contactsd: {
    desc: "Contacts database service.",
  },
  remindd: {
    desc: "Reminders app sync.",
  },
  calaccessd: {
    desc: "Calendar access broker.",
  },
  callkitd: {
    desc: "CallKit — third-party VoIP call integration (WhatsApp, Skype, etc).",
  },
  amsengagementd: {
    desc: "Apple Media Services — App Store and iTunes Store engagement.",
  },
  ScreenTimeAgent: {
    desc: "Screen Time enforcement and reporting.",
  },
  screentimed: {
    desc: "Screen Time aggregator across devices.",
  },
  familycircled: {
    desc: "Family Sharing coordination.",
  },
  gamed: {
    desc: "Game Center.",
  },
  magicswitchd: {
    desc: "Universal Control / 'magic switch' between iPad and Mac.",
  },
  ScreenTimeCore: {
    desc: "Screen Time core service.",
  },
  silex: {
    desc: "A low-level system component used by managed configurations.",
  },
  parsec_fbf: {
    desc: "Parsec is Apple's internal name for Spotlight's web/knowledge results. fbf = feedback.",
  },
  parsecd: {
    desc: "Parsec — Spotlight's online knowledge results (web, dictionary, App Store).",
  },
  homeenergyd: {
    desc: "Home energy tracking for HomeKit-connected accessories.",
  },
  homeaccessoryupdater: {
    desc: "Installs firmware updates for HomeKit accessories.",
  },
};

window.lookupProcess = function (name) {
  const direct = window.IOS_PROCESSES[name];
  if (direct) return { ...direct, kind: classify(name) };
  return { desc: null, kind: classify(name) };
};

function classify(name) {
  if (!name) return "process";
  if (name.endsWith("d") && /[a-z]/.test(name[name.length - 2] || "")) {
    return "system daemon";
  }
  if (/^[A-Z]/.test(name)) return "app or framework";
  return "process";
}

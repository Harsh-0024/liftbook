# Liftbook for Android

The Android app is the web app in `web/` wrapped by [Capacitor](https://capacitorjs.com/docs):
`web/tools/build_app.js` copies `web/` into `build/www`, and `npx cap sync android` puts those
files inside the app. The app opens and works with no connection, and syncs with Supabase like
the website does. There is one codebase: every screen is the web app's. The Android-only
parts are this folder and `web/app/native.js`, which does nothing on the website.

App id `in.liftbook.app`, name "Liftbook".

## What the app does differently from the website

- **No offline copy (service worker).** The app already carries every file. The website's
  `sw.js` is left out of the app.
- **Its own data on the phone.** IndexedDB and the sign-in live in the app's WebView storage, at
  `https://localhost`. They stay until the app is uninstalled or signed out.
- **Emailed links** (confirming an account, resetting a password, changing email):
  1. In the app, the link is asked for with `https://beta.liftbook.in/?app=android` (`WEB_APP_URL`
     in `web/config.js`).
  2. That page passes the sign-in on to the app through `in.liftbook.app://auth#…`. On an Android
     phone it tries this straight away, and there is also a button.
  3. If the email was opened on a computer, "Continue in this browser" finishes the step there.

  Supabase already allows `https://beta.liftbook.in/**`, so nothing else is needed there.
  **At the switch to app.liftbook.in:** change `WEB_APP_URL` and build a new version.
- **Back button:** goes back a screen. On the home screen it puts the app in the background.
- **Sync** also runs when the app comes back to the front and when the network returns.
- **Profile photo:** the app asks whether to use the camera or the gallery.
- **Backup file and CSV:** they open Android's share sheet (save to Files, Drive, email…).
- **Status bar:** its icons follow the app's light or dark theme. On older WebViews (below 140)
  the bars get the page colour instead of the page drawing behind them.

## Tools needed (once)

- **Java 21:** `brew install openjdk@21`. Android's build tools don't run on Java 11 or 24.
- **Android SDK:** `~/Library/Android/sdk`, with platform 36 and build-tools 35+.
- **`android/local.properties`:** one line, `sdk.dir=/Users/<you>/Library/Android/sdk`. It is not
  kept in git.
- **Node packages:** `npm install` in the project folder.

Set Java 21 for the shell you build in:

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
```

## Debug build (to install on a phone or emulator)

```bash
npm run android:debug
```

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`. Install it with
`adb install -r android/app/build/outputs/apk/debug/app-debug.apk`, or copy it to the phone and
open it ("install unknown apps" must be allowed for the app that opens it).

After changing anything in `web/`, run `npm run android:debug` again. It copies the files and
rebuilds.

## Release build for the Play Store (AAB)

The upload key, and its passwords, stay on your Mac in `~/.liftbook-android/`, outside the repo.
**Back up that folder** (e.g. in a password manager). Without it you can't publish updates,
unless you have Google reset the upload key.

### 1. Make the upload key (once)

```bash
mkdir -p ~/.liftbook-android && chmod 700 ~/.liftbook-android
```

```bash
keytool -genkeypair -v -keystore ~/.liftbook-android/liftbook-upload.jks -alias liftbook -keyalg RSA -keysize 2048 -validity 10000
```

`keytool` asks for a password and your name. Type them in the terminal, not in a file or a chat.

### 2. Tell the build where the key is (once)

Create `~/.liftbook-android/keystore.properties` with a text editor:

```
storeFile=/Users/<you>/.liftbook-android/liftbook-upload.jks
storePassword=<the password>
keyAlias=liftbook
keyPassword=<the password>
```

Then:

```bash
chmod 600 ~/.liftbook-android/keystore.properties
```

`android/app/build.gradle` reads this file when it exists. Without it the release build comes
out unsigned.

### 3. Build

Before each release, raise `versionCode` (by 1) and `versionName` in `android/app/build.gradle`.
Then:

```bash
npm run android:release
```

The file to upload is `android/app/build/outputs/bundle/release/app-release.aab`.

### 4. Play Console (when you decide to publish)

At [play.google.com/console](https://play.google.com/console), create the app with package
`in.liftbook.app`. Turn on Play App Signing (the default), then upload the AAB to the internal
testing track first. Google keeps the real signing key. Yours is only the upload key.

## Icons and splash

The sources are in `android/icon-source/` (made from `web/icons/`). To regenerate:

```bash
npx capacitor-assets generate --android --assetPath android/icon-source --iconBackgroundColor '#000000' --splashBackgroundColor '#000000' --splashBackgroundColorDark '#000000'
```

Then put back the two adaptive icon files, `android/app/src/main/res/mipmap-anydpi-v26/*.xml`
(`git checkout` them). The generator writes ones that point at a background image that doesn't
exist.

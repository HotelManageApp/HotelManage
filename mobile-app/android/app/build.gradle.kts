import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// google-services.json is not committed (SPEC-notifications): developers drop it into
// android/app/, CI decodes it from GOOGLE_SERVICES_JSON_B64. Without it the app builds
// and runs with push disabled.
if (file("google-services.json").exists()) {
    apply(plugin = "com.google.gms.google-services")
}

// Release signing (T57). The keystore is never committed: locally android/key.properties
// (git-ignored) points to it; CI writes the same file from repository secrets. Without it a
// release build fails, unless HOTEL_ALLOW_DEBUG_SIGNING=1 (local smoke builds only — such an
// APK cannot be updated by the real one and must not be handed to guests).
val keyProperties = Properties().apply {
    val file = rootProject.file("key.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}
val hasReleaseKey = listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
    .all { !keyProperties.getProperty(it).isNullOrBlank() }
val allowDebugSigning = System.getenv("HOTEL_ALLOW_DEBUG_SIGNING") == "1"

android {
    namespace = "vn.hotelmanage.hotel_guest"
    // flutter_local_notifications needs to compile against API 37; targetSdk is unchanged.
    compileSdk = maxOf(flutter.compileSdkVersion, 37)
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        // Required by flutter_local_notifications.
        isCoreLibraryDesugaringEnabled = true
    }

    defaultConfig {
        applicationId = "vn.hotelmanage.hotel_guest"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseKey) {
            create("release") {
                storeFile = rootProject.file(keyProperties.getProperty("storeFile"))
                storePassword = keyProperties.getProperty("storePassword")
                keyAlias = keyProperties.getProperty("keyAlias")
                keyPassword = keyProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = when {
                hasReleaseKey -> signingConfigs.getByName("release")
                allowDebugSigning -> signingConfigs.getByName("debug")
                else -> null
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

// Fail early and clearly instead of producing an unsigned or debug-signed release APK.
gradle.taskGraph.whenReady {
    val buildsRelease = allTasks.any { it.name.contains("Release") && it.project == project }
    if (buildsRelease && !hasReleaseKey && !allowDebugSigning) {
        throw GradleException(
            "Release signing key missing: create android/key.properties (see docs/release-apk.md) " +
                "or set HOTEL_ALLOW_DEBUG_SIGNING=1 for a local smoke build."
        )
    }
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.5")
}

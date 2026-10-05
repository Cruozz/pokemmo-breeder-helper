plugins {
  alias(libs.plugins.android.application)
  alias(libs.plugins.compose.compiler)
  alias(libs.plugins.kotlin.serialization)
  id("com.chaquo.python")
}

val plannerRulesVersion = Regex("(?m)^RULES_VERSION = \"([^\"]+)\"")
    .find(file("src/main/python/mobile_bridge.py").readText())!!.groupValues[1]

android {
    namespace = "com.example.pokemmobreederhelper"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.example.pokemmobreederhelper"
        minSdk = 26
        targetSdk = 36
        versionCode = 11
        versionName = "0.5.1"
        buildConfigField("String", "PLANNER_RULES_VERSION", "\"$plannerRulesVersion\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
          abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
      compose = true
      aidl = false
      buildConfig = true
      shaders = false
    }

    packaging {
      resources {
        excludes += "/META-INF/{AL2.0,LGPL2.1}"
      }
    }
}

kotlin {
    jvmToolchain(21)
}

val plannerPythonDir = layout.buildDirectory.dir("generated/python/planner")
val syncPlannerPython by tasks.registering(Sync::class) {
  from(rootProject.projectDir.parentFile) {
    include("models.py")
    include("storage.py")
    include("nature_data.py")
    include("species_data.py")
    include("reference_data.py")
    include("chain_planner.py")
    include("planner.py")
    include("execution.py")
    include("route_roles.py")
    include("data/**")
  }
  into(plannerPythonDir)
}

chaquopy {
  defaultConfig {
    version = "3.12"
    buildPython(providers.gradleProperty("plannerBuildPython").getOrElse(
      rootProject.projectDir.parentFile.resolve(".runtime/python312/python.exe").absolutePath))
  }
  sourceSets {
    getByName("main") {
      srcDir(plannerPythonDir)
    }
  }
}

tasks.named("preBuild").configure {
  dependsOn(syncPlannerPython)
}

tasks.matching { it.name.endsWith("PythonSources") }.configureEach {
  dependsOn(syncPlannerPython)
}

dependencies {
  val composeBom = platform(libs.androidx.compose.bom)
  implementation(composeBom)
  androidTestImplementation(composeBom)

  // Core Android dependencies
  implementation(libs.androidx.core.ktx)
  implementation(libs.androidx.lifecycle.runtime.ktx)
  implementation(libs.androidx.activity.compose)

  // Arch Components
  implementation(libs.androidx.lifecycle.runtime.compose)
  implementation(libs.androidx.lifecycle.viewmodel.compose)

  // Compose
  implementation(libs.androidx.compose.ui)
  implementation(libs.androidx.compose.ui.tooling.preview)
  implementation(libs.androidx.compose.material3)
  implementation(libs.kotlinx.serialization.json)
  // Tooling
  debugImplementation(libs.androidx.compose.ui.tooling)
  // Instrumented tests
  androidTestImplementation(libs.androidx.compose.ui.test.junit4)
  debugImplementation(libs.androidx.compose.ui.test.manifest)

  // Local tests: jUnit, coroutines, Android runner
  testImplementation(libs.junit)
  testImplementation(libs.kotlinx.coroutines.test)

  // Instrumented tests: jUnit rules and runners
  androidTestImplementation(libs.androidx.test.core)
  androidTestImplementation(libs.androidx.test.ext.junit)
  androidTestImplementation(libs.androidx.test.runner)
  androidTestImplementation(libs.androidx.test.espresso.core)

  // Navigation
  implementation(libs.androidx.navigation3.ui)
  implementation(libs.androidx.navigation3.runtime)
  implementation(libs.androidx.lifecycle.viewmodel.navigation3)
}

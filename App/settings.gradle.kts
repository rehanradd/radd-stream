pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

// Project name comes from the one brand file (<repo root>/brand.properties) so a
// re-skin also renames the Gradle/IDE project. Falls back only if the key is blank.
val brandName = run {
    val file = File(settingsDir.parentFile, "brand.properties")
    if (!file.exists()) return@run "radd-stream-app"
    val props = java.util.Properties()
    file.inputStream().use { props.load(it) }
    (props.getProperty("identity.name") ?: "").trim().lowercase().replace(' ', '-') + "-app"
}
rootProject.name = brandName.ifBlank { "radd-stream-app" }
include(":app")

"""Global Configurations for py.test runner"""

pytest_plugins = [
    "pytest_plugins.uncollector",
    # Component Fixture
    "pytest_fixtures.authsource_fixtures",
]

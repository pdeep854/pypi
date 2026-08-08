import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import publish_releases


def make_wheel(directory: Path, filename: str, name: str, version: str) -> Path:
    wheel = directory / filename
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"{name.replace('-', '_')}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
    return wheel


class PublishReleasesTest(unittest.TestCase):
    def test_distribution_directory_defaults_to_dist(self):
        self.assertEqual(publish_releases.distribution_directory({}), Path("dist"))
        self.assertEqual(
            publish_releases.distribution_directory({"DIST_DIR": "artifacts"}),
            Path("artifacts"),
        )

    def test_groups_wheels_by_embedded_metadata_not_filename(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            first = make_wheel(
                directory, "unexpected-name-one.whl", "Example-Project", "1.2.3"
            )
            second = make_wheel(
                directory, "unexpected-name-two.whl", "Example-Project", "1.2.3"
            )
            other = make_wheel(directory, "another-file.whl", "other.project", "4.5.6")
            grouped = publish_releases.wheels_by_release([first, second, other])

        self.assertEqual(set(grouped), {"Example-Project@1.2.3", "other.project@4.5.6"})
        self.assertEqual(set(grouped["Example-Project@1.2.3"]), {first, second})

    def test_existing_release_uploads_and_missing_release_creates(self):
        calls = []

        class Result:
            def __init__(self, returncode):
                self.returncode = returncode

        def run(command, **kwargs):
            calls.append((command, kwargs))
            if command[:3] == ["gh", "release", "view"]:
                return Result(0 if command[3] == "existing@1" else 1)
            return Result(0)

        publish_releases.publish_releases(
            {"existing@1": [Path("existing.whl")], "new@2": [Path("new.whl")]},
            "halide/pypi",
            "Build wheels",
            run=run,
        )

        commands = [command for command, _ in calls]
        self.assertIn(
            [
                "gh",
                "release",
                "upload",
                "existing@1",
                "existing.whl",
                "--repo",
                "halide/pypi",
                "--clobber",
            ],
            commands,
        )
        self.assertIn(
            [
                "gh",
                "release",
                "create",
                "new@2",
                "new.whl",
                "--repo",
                "halide/pypi",
                "--title",
                "new@2",
                "--notes",
                "Automated build from Build wheels",
            ],
            commands,
        )


if __name__ == "__main__":
    unittest.main()

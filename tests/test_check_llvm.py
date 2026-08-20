import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import check_llvm


class CheckLlvmTest(unittest.TestCase):
    def test_release_tag_matches_its_wheel(self):
        build, resolved = check_llvm.should_build(
            "llvmorg-21.1.8",
            ["halide_llvm-21.1.8-py3-none-any.whl"],
        )
        self.assertFalse(build)
        self.assertEqual(resolved, "llvmorg-21.1.8")

    def test_dev_ref_uses_resolved_commit_prefix(self):
        build, resolved = check_llvm.should_build(
            "main",
            ["halide_llvm-22.0.0.dev1+gdeadbeef-py3-none-any.whl"],
            tag_version=lambda _: None,
            commit_info=lambda _: ("deadbeef0123456789", 1),
        )
        self.assertFalse(build)
        self.assertEqual(resolved, "deadbeef0123456789")

    def test_latest_tag_for_major_prefers_final_release_over_later_rc(self):
        refs = [
            {"ref": "refs/tags/llvmorg-22.1.0-rc1"},
            {"ref": "refs/tags/llvmorg-22.1.0"},
            {"ref": "refs/tags/llvmorg-22.1.0-rc2"},
            {"ref": "refs/tags/llvmorg-22.1.1"},
        ]
        tag = check_llvm.latest_tag_for_major(22, fetch=lambda _: refs)
        self.assertEqual(tag, "llvmorg-22.1.1")

    def test_latest_tag_for_major_falls_back_to_highest_rc(self):
        refs = [
            {"ref": "refs/tags/llvmorg-23.1.0-rc1"},
            {"ref": "refs/tags/llvmorg-23.1.0-rc3"},
            {"ref": "refs/tags/llvmorg-23.1.0-rc2"},
        ]
        tag = check_llvm.latest_tag_for_major(23, fetch=lambda _: refs)
        self.assertEqual(tag, "llvmorg-23.1.0-rc3")

    def test_latest_tag_for_major_returns_none_when_untagged(self):
        tag = check_llvm.latest_tag_for_major(24, fetch=lambda _: [])
        self.assertIsNone(tag)

    def test_candidate_refs_uses_explicit_ref_alone(self):
        refs = check_llvm.candidate_refs(
            "llvmorg-21.1.8",
            major_fetch=lambda: (_ for _ in ()).throw(AssertionError("unused")),
            tag_fetch=lambda major: (_ for _ in ()).throw(AssertionError("unused")),
        )
        self.assertEqual(refs, ["llvmorg-21.1.8"])

    def test_candidate_refs_discovers_main_and_two_prior_majors(self):
        tags = {23: "llvmorg-23.1.0-rc3", 22: "llvmorg-22.1.8"}
        refs = check_llvm.candidate_refs(
            None,
            major_fetch=lambda: 24,
            tag_fetch=lambda major: tags.get(major),
        )
        self.assertEqual(refs, ["main", "llvmorg-23.1.0-rc3", "llvmorg-22.1.8"])

    def test_candidate_refs_skips_untagged_prior_major(self):
        refs = check_llvm.candidate_refs(
            None,
            major_fetch=lambda: 24,
            tag_fetch=lambda major: "llvmorg-22.1.8" if major == 22 else None,
        )
        self.assertEqual(refs, ["main", "llvmorg-22.1.8"])

    def test_build_matrix_expands_only_refs_needing_wheels(self):
        matrix = check_llvm.build_matrix(
            ["llvmorg-21.1.8", "main"],
            ["halide_llvm-21.1.8-py3-none-any.whl"],
            tag_version=lambda ref: "21.1.8" if ref == "llvmorg-21.1.8" else None,
            commit_info=lambda _: ("deadbeef0123456789", 1),
        )
        self.assertEqual(len(matrix), len(check_llvm.PLATFORMS))
        self.assertTrue(all(entry["ref"] == "deadbeef0123456789" for entry in matrix))
        self.assertEqual(
            {entry["platform"] for entry in matrix},
            {platform["platform"] for platform in check_llvm.PLATFORMS},
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from backend import council
from backend import council_settings
from backend import council_presets
from backend import main
from backend.config import COUNCIL_MODELS


class CouncilStageDefaultsTest(unittest.TestCase):
    def test_build_default_stages_uses_chairman(self):
        members = [
            {"id": "member-1", "alias": "A", "model_id": COUNCIL_MODELS[0]},
            {"id": "member-2", "alias": "B", "model_id": COUNCIL_MODELS[0]},
        ]
        stages = council_settings.build_default_stages(members, "member-2")
        self.assertEqual(len(stages), 3)
        self.assertEqual(stages[0]["member_ids"], ["member-1", "member-2"])
        self.assertEqual(stages[2]["member_ids"], ["member-2"])

    def test_ensure_stage_config_adds_stages(self):
        settings = {
            "members": [
                {"id": "member-1", "alias": "A", "model_id": COUNCIL_MODELS[0]},
            ],
            "chairman_id": "member-1",
        }
        updated = council_settings.ensure_stage_config(settings)
        self.assertIn("stages", updated)
        self.assertEqual(len(updated["stages"]), 3)

    def test_ensure_stage_config_hydrates_stage_prompts(self):
        settings = {
            "members": [
                {"id": "member-1", "alias": "A", "model_id": COUNCIL_MODELS[0]},
            ],
            "chairman_id": "member-1",
            "stages": [
                {"id": "stage-2", "name": "Peer Rankings", "prompt": "", "execution_mode": "parallel", "member_ids": ["member-1"]},
                {"id": "stage-3", "name": "Final Synthesis", "prompt": "", "execution_mode": "sequential", "member_ids": ["member-1"]},
            ],
        }
        updated = council_settings.ensure_stage_config(settings)
        self.assertTrue(updated["stages"][0]["prompt"])
        self.assertTrue(updated["stages"][1]["prompt"])


class CouncilSettingsValidationTest(unittest.TestCase):
    def test_validate_council_settings_accepts_valid_stages(self):
        member = main.CouncilMemberConfig(
            id="member-1",
            alias="Member 1",
            model_id=COUNCIL_MODELS[0],
            system_prompt="",
        )
        stage = main.CouncilStageConfig(
            id="stage-1",
            name="Stage 1",
            prompt="",
            execution_mode="parallel",
            member_ids=["member-1"],
        )
        payload = main.CouncilSettingsRequest(
            members=[member],
            chairman_id="member-1",
            chairman_label="Chairman",
            title_model_id=COUNCIL_MODELS[0],
            use_system_prompt_stage2=True,
            use_system_prompt_stage3=True,
            stages=[stage],
        )
        with patch.object(main, "list_converse_models_for_region", return_value=[{"id": COUNCIL_MODELS[0]}]):
            errors = main._validate_council_settings(payload)
        self.assertEqual(errors, [])

    def test_validate_council_settings_enforces_stage_member_limit(self):
        member = main.CouncilMemberConfig(
            id="member-1",
            alias="Member 1",
            model_id=COUNCIL_MODELS[0],
            system_prompt="",
        )
        stage = main.CouncilStageConfig(
            id="stage-1",
            name="Stage 1",
            prompt="",
            execution_mode="parallel",
            member_ids=["member-1"] * 6,
        )
        payload = main.CouncilSettingsRequest(
            members=[member],
            chairman_id="member-1",
            chairman_label="Chairman",
            title_model_id=COUNCIL_MODELS[0],
            use_system_prompt_stage2=True,
            use_system_prompt_stage3=True,
            stages=[stage],
        )
        with patch.object(main, "list_converse_models_for_region", return_value=[{"id": COUNCIL_MODELS[0]}]):
            errors = main._validate_council_settings(payload)
        self.assertTrue(any("exceeds max members" in error for error in errors))


class CouncilPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_full_council_uses_pipeline_metadata(self):
        stage1_results = [
            {"model": "Alpha", "response": "A", "status": "ok"},
            {"model": "Beta", "response": "B", "status": "ok"},
        ]
        stage2_results = [
            {"model": "Alpha", "ranking": "FINAL RANKING:\n1. Response A\n2. Response B"}
        ]
        label_to_model = {"Response A": "Alpha", "Response B": "Beta"}
        stage3_result = {"model": "Chairman", "response": "Final"}

        with patch.object(council, "_collect_stage_responses", return_value=stage1_results), \
            patch.object(council, "stage2_collect_rankings", return_value=(stage2_results, label_to_model)), \
            patch.object(council, "stage3_synthesize_final", return_value=stage3_result):
            result_stage1, result_stage2, result_stage3, metadata, stages = await council.run_full_council("Question")

        self.assertEqual(result_stage1, stage1_results)
        self.assertEqual(result_stage2, stage2_results)
        self.assertEqual(result_stage3, stage3_result)
        self.assertIn("aggregate_rankings", metadata)
        self.assertEqual(metadata["aggregate_rankings"][0]["model"], "Alpha")
        self.assertEqual(metadata["aggregate_rankings"][0]["average_rank"], 1.0)
        self.assertEqual(len(stages), 3)

    async def test_run_full_council_includes_stage_prompts(self):
        settings = {
            "members": [
                {"id": "member-1", "alias": "Alpha", "model_id": COUNCIL_MODELS[0], "system_prompt": ""},
            ],
            "chairman_id": "member-1",
            "stages": [
                {
                    "id": "stage-1",
                    "name": "Brainstorm",
                    "prompt": "Focus on key ideas.",
                    "execution_mode": "parallel",
                    "member_ids": ["member-1"],
                },
            ],
        }
        stage1_results = [{"model": "Alpha", "response": "A", "status": "ok"}]
        with patch.object(council, "get_settings", return_value=settings), \
            patch.object(council, "_collect_stage_responses", return_value=stage1_results):
            _, _, _, _, stages = await council.run_full_council("Question")
        self.assertEqual(stages[0]["name"], "Brainstorm")
        self.assertEqual(stages[0]["prompt"], "Focus on key ideas.")


class CouncilPresetsTest(unittest.TestCase):
    def test_default_preset_cannot_be_updated(self):
        with patch.object(council_presets, "_ensure_defaults"), \
            patch.object(
                council_presets,
                "_find_preset_by_name",
                return_value={"id": "default", "name": council_presets.DEFAULT_PRESET_NAME},
            ):
            with self.assertRaises(ValueError):
                council_presets.create_preset(council_presets.DEFAULT_PRESET_NAME, {})


if __name__ == "__main__":
    unittest.main()

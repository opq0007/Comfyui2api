from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from comfyui2api.workflow_params import (
    WorkflowParameterDefinition,
    WorkflowParamTarget,
    apply_img2img_resize_params,
    detect_parameter_candidates,
    generate_parameter_template,
    load_workflow_parameter_spec,
    normalize_parameter_value,
    resolve_standard_overrides,
)


class WorkflowParameterMappingTests(unittest.TestCase):
    def test_sidecar_mapping_converts_size_fps_duration_and_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workflows_dir = root / "workflows"
            sidecar_dir = workflows_dir / ".comfyui2api"
            workflows_dir.mkdir(parents=True, exist_ok=True)
            sidecar_dir.mkdir(parents=True, exist_ok=True)

            workflow_path = workflows_dir / "video_flow.json"
            workflow_obj = {
                "prompt": {
                    "10": {
                        "class_type": "EmptyLatentImage",
                        "inputs": {"width": 512, "height": 512},
                        "_meta": {"title": "Latent Size"},
                    },
                    "11": {
                        "class_type": "KSampler",
                        "inputs": {"seed": 1},
                        "_meta": {"title": "Sampler"},
                    },
                    "20": {
                        "class_type": "VideoCombine",
                        "inputs": {"fps": 12, "frames": 48},
                        "_meta": {"title": "Video Output"},
                    },
                    "30": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "sample"}},
                }
            }
            workflow_path.write_text(json.dumps(workflow_obj, ensure_ascii=False), encoding="utf-8")

            sidecar = {
                "version": 1,
                "kind": "txt2video",
                "parameters": {
                    "size": {
                        "type": "size",
                        "maps": [
                            {"target": "10.width", "part": "width"},
                            {
                                "target": {
                                    "selector": {
                                        "class_type": "EmptyLatentImage",
                                        "title": "Latent Size",
                                        "input_key": "height",
                                    }
                                },
                                "part": "height",
                            },
                        ],
                    },
                    "fps": {
                        "type": "int",
                        "default": 12,
                        "maps": [
                            {
                                "target": {
                                    "selector": {
                                        "class_type": "VideoCombine",
                                        "title": "Video Output",
                                        "input_key": "fps",
                                    }
                                }
                            }
                        ],
                    },
                    "duration": {
                        "type": "float",
                        "maps": [
                            {"target": "20.frames", "transform": "seconds_to_frames", "fps_param": "fps", "round": "ceil"}
                        ],
                    },
                    "seed": {
                        "type": "int",
                        "maps": [{"target": "11.seed"}],
                    },
                },
            }
            (sidecar_dir / "video_flow.params.json").write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")

            spec = load_workflow_parameter_spec(
                workflows_dir=workflows_dir,
                workflow_path=workflow_path,
                expected_kind="txt2video",
            )
            self.assertIsNotNone(spec)

            overrides = resolve_standard_overrides(
                workflow_obj=workflow_obj,
                spec=spec,
                request_params={"size": "1024x768", "fps": 24, "duration": 5, "seed": 7},
            )

            self.assertEqual(
                overrides,
                [
                    ("10", "width", 1024),
                    ("10", "height", 768),
                    ("11", "seed", 7),
                    ("20", "fps", 24),
                    ("20", "frames", 120),
                ],
            )

            detected = detect_parameter_candidates(workflow_obj)
            self.assertEqual(detected["size"][0]["maps"][0]["ref"], "10.width")
            self.assertEqual(detected["size"][0]["maps"][1]["ref"], "10.height")
            self.assertEqual(detected["fps"][0]["maps"][0]["ref"], "20.fps")
            self.assertEqual(detected["duration"][0]["maps"][0]["ref"], "20.frames")
            self.assertEqual(detected["duration"][0]["maps"][0]["transform"], "seconds_to_frames")
            self.assertEqual(detected["duration"][0]["paired_fps_ref"], "20.fps")

            template = generate_parameter_template(workflow_obj=workflow_obj, kind="txt2video", spec=spec)
            self.assertEqual(template["parameters"]["size"]["maps"][0]["target"]["ref"], "10.width")
            self.assertEqual(template["parameters"]["fps"]["default"], 12)
            self.assertEqual(template["parameters"]["duration"]["maps"][0]["transform"], "seconds_to_frames")
            self.assertEqual(template["parameters"]["duration"]["maps"][0]["fps_param"], "fps")

    def test_z_image_turbo_fp16_sidecar_maps_size_n_and_seed(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        workflows_dir = project_root / "comfyui-api-workflows"
        workflow_path = workflows_dir / "z_image_turbo_fp16.json"
        workflow_obj = json.loads(workflow_path.read_text(encoding="utf-8"))

        spec = load_workflow_parameter_spec(
            workflows_dir=workflows_dir,
            workflow_path=workflow_path,
            expected_kind="txt2img",
        )
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.prompt_node, "67.text")

        overrides = resolve_standard_overrides(
            workflow_obj=workflow_obj,
            spec=spec,
            request_params={"size": "768x512", "n": 3, "seed": 42, "steps": 6, "cfg": 1.5},
        )
        self.assertEqual(
            overrides,
            [
                ("68", "width", 768),
                ("68", "height", 512),
                ("68", "batch_size", 3),
                ("70", "steps", 6),
                ("70", "cfg", 1.5),
                ("70", "seed", 42),
            ],
        )

        width_only = resolve_standard_overrides(
            workflow_obj=workflow_obj,
            spec=spec,
            request_params={"width": 640, "height": 480},
        )
        self.assertIn(("68", "width", 640), width_only)
        self.assertIn(("68", "height", 480), width_only)

        detected = detect_parameter_candidates(workflow_obj)
        self.assertEqual(detected["size"][0]["maps"][0]["ref"], "68.width")
        self.assertEqual(detected["n"][0]["maps"][0]["ref"], "68.batch_size")
        self.assertEqual(detected["seed"][0]["maps"][0]["ref"], "70.seed")

    def test_kaggle_flux2_edit_sidecar_maps_second_image_and_input_count(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        workflows_dir = project_root / "comfyui-api-workflows"
        workflow_path = workflows_dir / "kaggle_flux2_klein_9b_kv_image_edit_api.json"
        workflow_obj = json.loads(workflow_path.read_text(encoding="utf-8"))

        spec = load_workflow_parameter_spec(
            workflows_dir=workflows_dir,
            workflow_path=workflow_path,
            expected_kind="img2img",
        )
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.prompt_node, "135.text")
        self.assertEqual(spec.image_node, "76.image")
        self.assertEqual(spec.parameters["inputImgCount"].default, 1)

        single = resolve_standard_overrides(workflow_obj=workflow_obj, spec=spec, request_params={})
        self.assertIn(("705", "value", 1), single)

        overrides = resolve_standard_overrides(
            workflow_obj=workflow_obj,
            spec=spec,
            request_params={
                "n": 2,
                "steps": 8,
                "cfg": 1.2,
                "seed": 11,
                "image2": "uploads/second.png",
                "inputImgCount": 2,
            },
        )
        self.assertEqual(
            overrides,
            [
                ("129", "batch_size", 2),
                ("137", "steps", 8),
                ("138", "cfg", 1.2),
                ("125", "noise_seed", 11),
                ("718", "value", False),
                ("81", "image", "uploads/second.png"),
                ("705", "value", 2),
            ],
        )

        sized = resolve_standard_overrides(
            workflow_obj=workflow_obj,
            spec=spec,
            request_params=apply_img2img_resize_params({"size": "1024x768"}),
        )
        self.assertIn(("718", "value", True), sized)
        self.assertIn(("720", "value", 1024), sized)
        self.assertIn(("721", "value", 768), sized)

        both_dims = resolve_standard_overrides(
            workflow_obj=workflow_obj,
            spec=spec,
            request_params=apply_img2img_resize_params({"width": 640, "height": 480}),
        )
        self.assertIn(("718", "value", True), both_dims)
        self.assertIn(("720", "value", 640), both_dims)
        self.assertIn(("721", "value", 480), both_dims)

        width_only = resolve_standard_overrides(
            workflow_obj=workflow_obj,
            spec=spec,
            request_params=apply_img2img_resize_params({"width": 1024, "resizeFlag": True}),
        )
        self.assertIn(("718", "value", False), width_only)
        self.assertNotIn(("720", "value", 1024), width_only)

    def test_apply_img2img_resize_params_forces_flag_from_complete_size(self) -> None:
        self.assertEqual(apply_img2img_resize_params({}), {"resizeFlag": False})
        self.assertEqual(
            apply_img2img_resize_params({"size": "1024x768", "resizeFlag": False}),
            {"size": "1024x768", "resizeFlag": True},
        )
        self.assertEqual(
            apply_img2img_resize_params({"width": 640, "height": 480}),
            {"width": 640, "height": 480, "resizeFlag": True},
        )
        self.assertEqual(
            apply_img2img_resize_params({"width": 1024, "resizeFlag": True}),
            {"resizeFlag": False},
        )
        self.assertEqual(
            apply_img2img_resize_params({"size": "  ", "width": "", "resizeFlag": True}),
            {"size": "  ", "width": "", "resizeFlag": False},
        )

    def test_bool_parameter_normalizes_common_truthy_values(self) -> None:
        spec = WorkflowParameterDefinition(
            name="resizeFlag",
            type="bool",
            maps=(WorkflowParamTarget(ref="718.value"),),
        )
        self.assertIs(normalize_parameter_value(spec, True), True)
        self.assertIs(normalize_parameter_value(spec, "false"), False)
        self.assertIs(normalize_parameter_value(spec, 1), True)
        self.assertIs(normalize_parameter_value(spec, "0"), False)
        with self.assertRaises(ValueError):
            normalize_parameter_value(spec, "yes")

    def test_sidecar_mapping_loads_explicit_prompt_and_image_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workflows_dir = root / "workflows"
            sidecar_dir = workflows_dir / ".comfyui2api"
            workflows_dir.mkdir(parents=True, exist_ok=True)
            sidecar_dir.mkdir(parents=True, exist_ok=True)

            workflow_path = workflows_dir / "hybrid_flow.json"
            workflow_obj = {
                "prompt": {
                    "1": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
                    "2": {"class_type": "CustomPromptNode", "inputs": {"custom_prompt": "hello"}},
                    "3": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "sample"}},
                }
            }
            workflow_path.write_text(json.dumps(workflow_obj, ensure_ascii=False), encoding="utf-8")

            sidecar = {
                "version": 1,
                "kind": "img2video",
                "prompt_node": "2.custom_prompt",
                "image_node": "1.image",
                "parameters": {
                    "duration": {
                        "type": "float",
                        "maps": [{"target": "4.value"}],
                    }
                },
            }
            (sidecar_dir / "hybrid_flow.params.json").write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")

            spec = load_workflow_parameter_spec(
                workflows_dir=workflows_dir,
                workflow_path=workflow_path,
                expected_kind="img2video",
            )

            self.assertIsNotNone(spec)
            assert spec is not None
            self.assertEqual(spec.prompt_node, "2.custom_prompt")
            self.assertEqual(spec.image_node, "1.image")
            self.assertEqual(spec.negative_prompt_node, "")

    def test_sidecar_mapping_supports_custom_string_and_image_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            workflows_dir = root / "workflows"
            sidecar_dir = workflows_dir / ".comfyui2api"
            workflows_dir.mkdir(parents=True, exist_ok=True)
            sidecar_dir.mkdir(parents=True, exist_ok=True)

            workflow_path = workflows_dir / "dual_input.json"
            workflow_obj = {
                "prompt": {
                    "437": {"class_type": "LoadImage", "inputs": {"image": "primary.png"}},
                    "440": {"class_type": "LoadImage", "inputs": {"image": "secondary.png"}},
                    "438": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "prompt one"}},
                    "325": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "prompt two"}},
                    "500": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "sample"}},
                }
            }
            workflow_path.write_text(json.dumps(workflow_obj, ensure_ascii=False), encoding="utf-8")

            sidecar = {
                "version": 1,
                "kind": "img2video",
                "prompt_node": "438.value",
                "image_node": "437.image",
                "parameters": {
                    "prompt2": {"type": "string", "maps": [{"target": "325.value"}]},
                    "image2": {"type": "image", "maps": [{"target": "440.image"}]},
                },
            }
            (sidecar_dir / "dual_input.params.json").write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")

            spec = load_workflow_parameter_spec(
                workflows_dir=workflows_dir,
                workflow_path=workflow_path,
                expected_kind="img2video",
            )

            self.assertIsNotNone(spec)
            overrides = resolve_standard_overrides(
                workflow_obj=workflow_obj,
                spec=spec,
                request_params={"prompt2": "secondary prompt", "image2": "uploads/second.png"},
            )

            self.assertEqual(
                overrides,
                [
                    ("325", "value", "secondary prompt"),
                    ("440", "image", "uploads/second.png"),
                ],
            )


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_local.config import load_config
from atlas_local.discovery import (
    RecommendedModel,
    _estimate_model_fit,
    _normalize_windows_gpu_entries,
    _resolve_windows_system_label,
    build_discovery_report,
)
from atlas_local.llm import OllamaCatalogSnapshot, OllamaModelInfo


class DiscoveryReportTests(unittest.TestCase):
    @patch("atlas_local.discovery.list_installed_ollama_model_names")
    @patch("atlas_local.discovery.detect_local_hardware")
    def test_report_marks_memory_degraded_and_falls_back_to_installed_chat_model(
        self,
        detect_local_hardware_mock,
        list_installed_models_mock,
    ) -> None:
        detect_local_hardware_mock.return_value = {
            "os": "Windows 11",
            "platform": "win32",
            "cpu": {"model": "AMD Ryzen", "logical_cores": 16},
            "memory": {"total_gb": 32.0},
            "gpus": [{"name": "RTX 4070", "memory_gb": 12.0}],
            "detection": {"confidence": "full", "notes": []},
        }
        list_installed_models_mock.return_value = ["gemma3:4b"]

        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(
                project_root=Path(temp_dir),
                env={
                    "CHAT_MODEL": "gpt-oss:20b",
                    "EMBED_MODEL": "nomic-embed-text:latest",
                },
            )
            catalog = OllamaCatalogSnapshot(
                models=(OllamaModelInfo(name="gemma3:4b", supports_images=True),),
                ollama_online=True,
                has_local_models=True,
                source="ollama",
            )

            payload = build_discovery_report(config, catalog)

        self.assertEqual(payload["atlas"]["status"], "memory-degraded")
        self.assertEqual(payload["atlas"]["effective_chat_model"], "gemma3:4b")
        self.assertEqual(payload["atlas"]["effective_chat_model_source"], "fallback")
        self.assertFalse(payload["atlas"]["configured_chat_model_installed"])
        self.assertFalse(payload["atlas"]["configured_embed_model_installed"])
        self.assertIn("fall back", payload["atlas"]["notes"][0])
        self.assertEqual(payload["installed_models"][0]["atlas_role"], "vision")

    @patch("atlas_local.discovery.list_installed_ollama_model_names")
    @patch("atlas_local.discovery.detect_local_hardware")
    def test_report_marks_ready_when_configured_models_are_installed(
        self,
        detect_local_hardware_mock,
        list_installed_models_mock,
    ) -> None:
        detect_local_hardware_mock.return_value = {
            "os": "Windows 11",
            "platform": "win32",
            "cpu": {"model": "AMD Ryzen", "logical_cores": 16},
            "memory": {"total_gb": 64.0},
            "gpus": [{"name": "RTX 4090", "memory_gb": 24.0}],
            "detection": {"confidence": "full", "notes": []},
        }
        list_installed_models_mock.return_value = ["gpt-oss:20b", "nomic-embed-text:latest"]

        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(
                project_root=Path(temp_dir),
                env={
                    "CHAT_MODEL": "gpt-oss:20b",
                    "EMBED_MODEL": "nomic-embed-text:latest",
                },
            )
            catalog = OllamaCatalogSnapshot(
                models=(OllamaModelInfo(name="gpt-oss:20b", supports_reasoning=True),),
                ollama_online=True,
                has_local_models=True,
                source="ollama",
            )

            payload = build_discovery_report(config, catalog)

        self.assertEqual(payload["atlas"]["status"], "ready")
        self.assertEqual(payload["atlas"]["effective_chat_model"], "gpt-oss:20b")
        self.assertTrue(payload["atlas"]["configured_chat_model_installed"])
        self.assertTrue(payload["atlas"]["configured_embed_model_installed"])
        self.assertEqual(payload["recommended_models"][0]["name"], "gpt-oss:20b")
        self.assertEqual(payload["recommended_models"][0]["fit"], "good")
        recommended_names = [item["name"] for item in payload["recommended_models"]]
        self.assertIn("llama3.1:8b", recommended_names)
        self.assertIn("qwen3:8b", recommended_names)
        self.assertIn("deepseek-r1:8b", recommended_names)
        self.assertNotIn("qwen2.5:7b", recommended_names)

    @patch("atlas_local.discovery.platform.version", return_value="10.0.26200")
    @patch("atlas_local.discovery.platform.release", return_value="10")
    def test_windows_build_above_22000_maps_to_windows_11(self, release_mock, version_mock) -> None:
        self.assertEqual(_resolve_windows_system_label(), "Windows 11")

    def test_windows_gpu_entries_prefer_nvidia_runtime_and_hide_integrated_vram(self) -> None:
        payload = [
            {"Name": "NVIDIA GeForce RTX 4080 Laptop GPU", "AdapterRAM": 4293918720},
            {"Name": "Intel(R) UHD Graphics", "AdapterRAM": 2147479552},
        ]

        gpus = _normalize_windows_gpu_entries(
            payload,
            nvidia_gpus=[
                {
                    "name": "NVIDIA GeForce RTX 4080 Laptop GPU",
                    "memory_gb": 12.0,
                    "kind": "dedicated",
                    "memory_source": "nvidia-smi",
                }
            ],
        )

        self.assertEqual(gpus[0]["name"], "NVIDIA GeForce RTX 4080 Laptop GPU")
        self.assertEqual(gpus[0]["memory_gb"], 12.0)
        self.assertEqual(gpus[0]["kind"], "dedicated")
        self.assertEqual(gpus[0]["memory_source"], "nvidia-smi")
        self.assertEqual(gpus[1]["kind"], "integrated")
        self.assertIsNone(gpus[1]["memory_gb"])
        self.assertEqual(gpus[1]["memory_source"], "shared")

    def test_fit_estimation_ignores_integrated_gpu_memory(self) -> None:
        candidate = RecommendedModel(
            name="qwen3:8b",
            title="Current Qwen all-rounder",
            use_case="reasoning",
            atlas_role="chat",
            min_ram_gb=12.0,
            good_ram_gb=18.0,
            min_vram_gb=8.0,
            good_vram_gb=12.0,
        )
        system = {
            "memory": {"total_gb": 20.0},
            "gpus": [
                {"name": "Intel(R) UHD Graphics", "memory_gb": 16.0, "kind": "integrated"},
            ],
        }

        fit, runtime, _reason = _estimate_model_fit(candidate, system)

        self.assertEqual(fit, "tight")
        self.assertEqual(runtime, "CPU")

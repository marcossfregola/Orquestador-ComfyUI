import unittest
from unittest.mock import patch


class F1310RuntimeRegressionTests(unittest.TestCase):
    def test_video_tools_resolve_bare_names_before_subprocess(self):
        from orquestador.adapters.video import FFmpegVideoAdapter

        with patch(
            "orquestador.adapters.video.shutil.which",
            side_effect=lambda value: f"C:/tools/{value}.exe",
        ):
            adapter = FFmpegVideoAdapter()
        self.assertEqual(adapter.ffprobe, "C:/tools/ffprobe.exe")
        self.assertEqual(adapter.ffmpeg, "C:/tools/ffmpeg.exe")

    def test_comfyui_output_wrapper_selects_only_durable_output(self):
        from orquestador.adapters.http import HistoryResult, HistoryState
        from orquestador.adapters.outputs import OutputCorrelationStatus, correlate_outputs
        from orquestador.domain.core import BackendJobRef

        ref = BackendJobRef("job")
        result = correlate_outputs(
            HistoryResult(
                ref,
                HistoryState.SUCCEEDED,
                {
                    "outputs": {
                        "127": {
                            "images": [
                                {"filename": "preview.png", "subfolder": "", "type": "temp"}
                            ],
                            "animated": [False],
                        },
                        "92": {
                            "images": [
                                {"filename": "chunk.mp4", "subfolder": "video", "type": "output"}
                            ],
                            "animated": [True],
                        },
                    }
                },
            ),
            ref,
        )
        self.assertEqual(result.status, OutputCorrelationStatus.VALID)
        self.assertEqual(tuple(item.filename for item in result.descriptors), ("chunk.mp4",))


if __name__ == "__main__":
    unittest.main()

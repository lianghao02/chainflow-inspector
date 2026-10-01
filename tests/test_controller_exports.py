import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from chain_fund_tracer.controller import Controller, dialog_path
from chain_fund_tracer.models import AnalysisResult


class DialogExportTests(unittest.TestCase):
    def controller(self, selection):
        controller = Controller.__new__(Controller)
        controller._current_result = AnalysisResult(query="0x" + "a" * 40)
        controller._window = SimpleNamespace(create_file_dialog=lambda *args, **kwargs: selection)
        return controller

    def test_dialog_path_handles_strings_sequences_and_cancellation(self):
        path = str(Path(tempfile.gettempdir()) / "中文 資料夾" / "分析包.zip")
        for selection in (path, (path,), [path], Path(path)):
            with self.subTest(selection_type=type(selection).__name__):
                self.assertEqual(dialog_path(selection), path)
                self.assertEqual(self.controller(selection).select_csv_file(), path)
        for selection in (None, "", (), []):
            with self.subTest(selection=selection):
                self.assertEqual(dialog_path(selection), "")
                self.assertTrue(self.controller(selection).export_report("agent_bundle")["cancelled"])

    def test_all_export_formats_accept_native_dialog_tuple(self):
        formats = {"csv": ".csv", "txt": ".txt", "svg": ".svg", "subpoena_csv": ".csv", "zip": ".zip", "agent_bundle": ".zip"}
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "中文 空白資料夾"
            target.mkdir()
            for name, extension in formats.items():
                with self.subTest(format=name):
                    path = target / (name + extension)
                    response = self.controller((str(path),)).export_report(name)
                    self.assertTrue(response["success"], response)
                    self.assertEqual(response["file_path"], str(path))
                    self.assertTrue(path.is_file())
                    if extension == ".zip":
                        with zipfile.ZipFile(path) as archive:
                            self.assertIsNone(archive.testzip())
                            if name == "agent_bundle":
                                self.assertEqual(len(archive.namelist()), 10)

    def test_agent_bundle_accepts_list_and_string(self):
        with tempfile.TemporaryDirectory() as folder:
            for index, kind in enumerate((str, list)):
                path = Path(folder) / f"bundle_{index}.zip"
                selection = str(path) if kind is str else [str(path)]
                self.assertTrue(self.controller(selection).export_report("agent_bundle")["success"])

    def test_failure_preserves_result_and_reports_recovery(self):
        controller = self.controller(("test.zip",))
        result = controller._current_result
        with patch("chain_fund_tracer.controller.export_agent_bundle", side_effect=PermissionError("無寫入權限")):
            response = controller.export_report("agent_bundle")
        self.assertFalse(response["success"])
        self.assertIn("請選擇可寫入的資料夾", response["error"])
        self.assertIs(controller._current_result, result)

    def test_dialog_failure_is_returned_to_frontend(self):
        controller = self.controller(None)
        controller._window.create_file_dialog = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("對話框失敗"))
        self.assertFalse(controller.export_report("agent_bundle")["success"])

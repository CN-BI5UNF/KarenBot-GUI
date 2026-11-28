"""Display-free behavior checks for settings drafts and the first-run wizard.

Run with a Python environment containing PyGObject and the host dependencies:
    python3 -m unittest discover -s tests -v
No widgets, runtime services, configuration files or network requests are created.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui import app as gui_app
from gui.pages import settings, settings_panels, setup


class Control:
    def __init__(self, text=""):
        self.text = text
        self.sensitive = True
        self.visible = True
        self.signals = {}
        self.controllers = []
        self.placeholder = ""
        self.children = []

    def connect(self, signal, callback):
        self.signals[signal] = callback

    def emit(self, signal):
        self.signals[signal](self)

    def add_controller(self, control):
        self.controllers.append(control)

    def get_text(self):
        return self.text

    def set_text(self, text):
        self.text = text
        if "changed" in self.signals:
            self.emit("changed")

    def set_sensitive(self, sensitive):
        self.sensitive = sensitive

    def set_visible(self, visible):
        self.visible = visible

    def set_placeholder_text(self, text):
        self.placeholder = text

    def add_css_class(self, css):
        pass

    def remove_css_class(self, css):
        pass

    def append(self, child):
        self.children.append(child)

    def set_halign(self, align):
        pass

    def set_hexpand(self, expand):
        pass


class Spin(Control):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value
        if "value-changed" in self.signals:
            self.emit("value-changed")


class TextArea:
    def __init__(self, text):
        self.buffer = Control(text)
        self.text_view = Control()
        self.text_view.get_buffer = lambda: self.buffer


class SettingsHarness:
    _bind_entry_commit = settings.SettingsPage._bind_entry_commit
    _bind_text_commit = settings.SettingsPage._bind_text_commit
    _put_secret = settings.SettingsPage._put_secret
    _track_draft = settings.SettingsPage._track_draft
    _sync_draft_hint = settings.SettingsPage._sync_draft_hint
    has_unsaved_changes = settings.SettingsPage.has_unsaved_changes
    _has_pending_saves = settings.SettingsPage._has_pending_saves
    can_discard_unsaved_changes = settings.SettingsPage.can_discard_unsaved_changes
    discard_unsaved_changes = settings.SettingsPage.discard_unsaved_changes

    def __init__(self):
        self._generic_drafts = {}
        self._pending_checks = {}
        self._saving_requests = 0
        self._group_panels = {}
        self._disposed = False
        self.draft_hint = Control()
        self.requests = []
        self.toast = Mock()
        self.update_spec_value = Mock()
        self.mark_restart = Mock()
        self.api = Mock()
        self.refresh = Mock()
        self.app = SimpleNamespace(window=None)

    def _save(self, field, value, **callbacks):
        self.requests.append((field, value, callbacks))

    def succeed(self, index=0):
        field, value, callbacks = self.requests[index]
        field["value"] = value
        callbacks["on_success"]({"value": value})

    def fail(self, index=0):
        self.requests[index][2]["on_error"](RuntimeError("write failed"))


class SettingsDraftTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(settings.Gtk, "EventControllerFocus", Control),
            patch.object(settings.Gtk, "EventControllerKey", Control),
            patch.object(settings.widgets, "text_value", lambda area: area.buffer.text),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.page = SettingsHarness()

    def editor(self, kind="list_str", text="old", value=None):
        area = TextArea(text)
        button = Control()
        field = {"path": "test.field", "type": kind,
                 "value": ["old"] if value is None else value}
        self.page._bind_text_commit(field, area, Control(), button)
        return area, button

    def test_text_typed_during_save_remains_unsaved(self):
        area, button = self.editor()
        area.buffer.set_text("first")
        area.commit_text()
        area.buffer.set_text("second")
        self.assertFalse(button.sensitive)
        self.page.succeed()
        self.assertEqual(self.page.requests[0][1], ["first"])
        self.assertEqual(area.buffer.text, "second")
        self.assertTrue(button.sensitive)
        self.assertTrue(self.page.has_unsaved_changes())
        area.commit_text()
        self.page.succeed(1)
        self.assertFalse(self.page.has_unsaved_changes())
        self.assertFalse(button.sensitive)

    def test_explicit_save_while_pending_sends_latest_once(self):
        area, _button = self.editor()
        area.buffer.set_text("first")
        area.commit_text()
        area.commit_text()  # focus-out followed by button click
        area.buffer.set_text("latest")
        area.commit_text()
        self.assertEqual(len(self.page.requests), 1)
        self.page.succeed()
        self.assertEqual(len(self.page.requests), 2)
        self.assertEqual(self.page.requests[1][1], ["latest"])
        self.page.succeed(1)
        self.assertFalse(self.page.has_unsaved_changes())

    def test_reverting_draft_while_pending_is_saved_after_first_response(self):
        area, _button = self.editor()
        area.buffer.set_text("first")
        area.commit_text()
        area.buffer.set_text("old")
        area.commit_text()
        self.page.succeed()
        self.assertEqual(self.page.requests[1][1], ["old"])

    def test_failed_json_save_preserves_text_for_retry(self):
        area, button = self.editor("json", '{"old": 1}', {"old": 1})
        area.buffer.set_text('{"new": 2}')
        area.commit_text()
        self.page.fail()
        self.assertEqual(area.buffer.text, '{"new": 2}')
        self.assertTrue(button.sensitive)
        self.assertTrue(self.page.has_unsaved_changes())
        area.commit_text()
        self.assertEqual(len(self.page.requests), 2)

    def test_invalid_json_remains_unsaved_without_request(self):
        area, _button = self.editor("json", "{}", {})
        area.buffer.set_text("{")
        area.commit_text()
        self.assertFalse(self.page.requests)
        self.assertTrue(self.page.has_unsaved_changes())
        self.page.toast.assert_called_once()

    def test_scalar_response_does_not_replace_newer_input(self):
        entry = Control("old")
        self.page._bind_entry_commit({"path": "name", "value": "old"}, entry, "str", Control())
        entry.set_text("first")
        entry.emit("activate")
        entry.set_text("second")
        self.page.succeed()
        self.assertEqual(entry.text, "second")
        self.assertTrue(self.page.has_unsaved_changes())
        entry.emit("activate")
        self.page.succeed(1)
        self.assertFalse(self.page.has_unsaved_changes())

    def test_invalid_scalar_keeps_user_input(self):
        entry = Control("10")
        self.page._bind_entry_commit({"path": "count", "value": 10}, entry, "int", Control())
        entry.set_text("invalid")
        entry.emit("activate")
        self.assertEqual(entry.text, "invalid")
        self.assertFalse(self.page.requests)
        self.assertTrue(self.page.has_unsaved_changes())

    def test_secret_binding_failure_preserves_reference_and_retries(self):
        field = {"path": "features.weather.api_key_id", "value": "old_key"}
        entry = Control("new-secret")
        self.page.api.put.return_value = {"ok": True}
        self.page.api.patch.side_effect = [RuntimeError("write failed"), {"value": "new_key"}]
        with patch.object(settings.widgets, "run_async", lambda call, on_success, on_error: on_success(call())):
            self.page._put_secret(field, "new_key", "new-secret", entry)
            self.assertEqual(field["value"], "old_key")
            self.assertEqual(entry.text, "new-secret")
            self.page.update_spec_value.assert_not_called()
            self.page._put_secret(field, "new_key", "new-secret", entry)
        self.assertEqual(self.page.api.patch.call_count, 2)
        self.assertEqual(field["value"], "new_key")
        self.assertEqual(entry.text, "")
        self.page.update_spec_value.assert_called_once_with(field["path"], "new_key")

    def test_numeric_settings_serialize_saves_and_keep_newer_value(self):
        spin = Spin(0)
        field = {"path": "count", "value": 0, "type": "int", "min": 0, "max": 100}
        with (
            patch.object(settings.Gtk, "Box", lambda **kwargs: Control()),
            patch.object(settings.widgets, "label", lambda *args, **kwargs: Control()),
            patch.object(settings.widgets, "muted", lambda *args, **kwargs: Control()),
            patch.object(settings.widgets, "spin_button", lambda *args, **kwargs: spin),
            patch.object(settings.GObject, "signal_lookup", lambda *args: True),
        ):
            settings.SettingsPage._field_row(self.page, field)
        spin.set_value(5)
        spin.emit("activate")
        spin.set_value(7)
        spin.emit("activate")
        self.assertEqual(len(self.page.requests), 1)
        self.page.succeed()
        self.assertEqual(spin.value, 7)
        self.assertEqual(self.page.requests[1][1], 7)
        self.page.fail(1)
        self.assertEqual(spin.value, 7)
        self.assertTrue(self.page.has_unsaved_changes())

    def test_disposed_settings_ignores_old_save_response(self):
        field = {"path": "count", "value": 1}
        callback = Mock()
        with patch.object(settings.widgets, "run_async") as runner:
            settings.SettingsPage._save(self.page, field, 2, on_success=callback)
        self.page._disposed = True
        runner.call_args.kwargs["on_success"]({"value": 2})
        self.assertEqual(field["value"], 1)
        self.page.update_spec_value.assert_not_called()
        callback.assert_not_called()

    def test_pending_save_prevents_discard_without_restoring_old_value(self):
        area, _button = self.editor()
        area.buffer.set_text("first")
        area.commit_text()
        area.buffer.set_text("second")
        area.commit_text()
        self.assertFalse(self.page.discard_unsaved_changes())
        self.assertEqual(area.buffer.text, "second")
        self.page.refresh.assert_not_called()
        self.page.succeed()
        self.assertEqual([request[1] for request in self.page.requests], [["first"], ["second"]])
        self.page.succeed(1)
        self.assertTrue(self.page.discard_unsaved_changes())
        self.assertFalse(self.page.has_unsaved_changes())

    def test_backup_directory_picker_updates_the_input_save_baseline(self):
        entry = Control("/old")
        field = {"path": "backup.directory", "value": "/old"}
        self.page._bind_entry_commit(field, entry, "str", Control())
        with patch.object(settings.widgets, "path_picker", return_value="/new"):
            settings.SettingsPage._pick_backup_dir(self.page, field, entry)
        self.assertEqual(self.page.requests[0][1], "/new")
        self.page.succeed()
        self.assertEqual(entry.text, "/new")
        self.assertFalse(self.page.has_unsaved_changes())

    def test_save_counter_is_cleared_on_failure(self):
        field = {"path": "enabled", "value": False}
        with patch.object(settings.widgets, "run_async") as runner:
            settings.SettingsPage._save(self.page, field, True)
        self.assertTrue(self.page.has_unsaved_changes())
        self.assertFalse(self.page.can_discard_unsaved_changes())
        runner.call_args.kwargs["on_error"](RuntimeError("offline"))
        self.assertEqual(self.page._saving_requests, 0)
        self.assertTrue(self.page.can_discard_unsaved_changes())

    def test_pending_navigation_waits_without_offering_discard(self):
        self.page._saving_requests = 1
        window = SimpleNamespace(_unsaved_dialog=None, current_page_id="settings", pages={"settings": self.page})
        navigate = Mock()
        with patch.object(gui_app.Adw.MessageDialog, "new") as dialog:
            gui_app.MainWindow._confirm_unsaved(window, heading="unsaved", body="draft", on_discard=navigate)
        dialog.assert_not_called()
        navigate.assert_not_called()

    def test_save_started_while_discard_dialog_open_blocks_its_response(self):
        area, _button = self.editor()
        area.buffer.set_text("first")
        window = SimpleNamespace(_unsaved_dialog=None, current_page_id="settings", pages={"settings": self.page})
        window._discard_current_unsaved = lambda: gui_app.MainWindow._discard_current_unsaved(window)
        navigate = Mock()
        dialog = Mock()
        with patch.object(gui_app.Adw.MessageDialog, "new", return_value=dialog):
            gui_app.MainWindow._confirm_unsaved(window, heading="unsaved", body="draft", on_discard=navigate)
        area.commit_text()  # focus-out can start a request after the dialog opens
        response = dialog.connect.call_args.args[1]
        response(dialog, "discard")
        navigate.assert_not_called()
        self.assertEqual(area.buffer.text, "first")
        self.assertIsNone(window._unsaved_dialog)
        self.page.succeed()
        self.assertFalse(self.page.has_unsaved_changes())

    def test_secret_clear_failure_keeps_config_reference(self):
        field = {"path": "features.weather.api_key_id", "value": "weather_key"}
        self.page.api.put.return_value = {"ok": True}
        self.page.api.patch.side_effect = RuntimeError("write failed")
        with patch.object(settings.widgets, "run_async", lambda call, on_success, on_error: on_success(call())):
            self.page._put_secret(field, "weather_key", "", Control())
        self.assertEqual(field["value"], "weather_key")
        self.page.update_spec_value.assert_not_called()

    def test_secret_clear_success_updates_cached_reference(self):
        field = {"path": "features.weather.api_key_id", "value": "weather_key"}
        self.page.api.put.return_value = {"ok": True}
        self.page.api.patch.return_value = {"value": ""}
        with patch.object(settings.widgets, "run_async", lambda call, on_success, on_error: on_success(call())):
            self.page._put_secret(field, "weather_key", "", Control())
        self.assertEqual(field["value"], "")
        self.page.update_spec_value.assert_called_once_with(field["path"], "")


class SetupBehaviorTests(unittest.TestCase):
    def payload_state(self):
        return SimpleNamespace(
            _provider={"id": "main", "model": "test-model", "api_key": "test-key"},
            _agents={}, _features={}, _adapter={}, _chat={}, _persona="test",
            _persona_source="builtin",
        )

    def test_zero_temperature_and_top_p_survive_payload(self):
        obj = self.payload_state()
        obj._chat = {"temperature": 0.0, "top_p": 0.0}
        obj._agents = {key: {"temperature": 0.0} for key, *_ in setup.SUB_AGENTS}
        result = setup.SetupPage._payload(obj)
        self.assertEqual(result["chat"]["temperature"], 0.0)
        self.assertEqual(result["chat"]["top_p"], 0.0)
        for agent in result["agents"].values():
            self.assertEqual(agent["temperature"], 0.0)

    def test_each_agent_uses_its_own_missing_defaults(self):
        result = setup.SetupPage._payload(self.payload_state())
        for key, _label, _desc, temperature, tokens in setup.SUB_AGENTS:
            self.assertEqual(result["agents"][key]["temperature"], temperature)
            self.assertEqual(result["agents"][key]["max_tokens"], tokens)

    def test_channel_is_optional_and_disabled_by_default(self):
        obj = self.payload_state()
        self.assertFalse(setup.SetupPage._payload(obj)["adapter"]["enabled"])
        obj._adapter = {"enabled": False, "host": "invalid host", "access_token": "无效"}
        self.assertIsNone(setup.SetupPage._validate_adapter(obj))
        obj._adapter["enabled"] = True
        self.assertIsNotNone(setup.SetupPage._validate_adapter(obj))
        self.assertTrue(setup.SetupPage._payload(obj)["adapter"]["enabled"])

    def test_summary_validation_identifies_the_step_to_correct(self):
        obj = SimpleNamespace(
            _path="recommended", _validate_provider_quick=lambda: None,
            _validate_provider_custom=lambda: None, _validate_agents=lambda: None,
            _validate_features=lambda: "missing feature key", _validate_embedding=lambda: None,
            _validate_adapter=lambda: None,
        )
        self.assertEqual(setup.SetupPage._validate_summary(obj), "missing feature key")
        self.assertEqual(obj._summary_error_step, "features")

    def test_edit_returns_directly_to_summary_after_validation(self):
        obj = SimpleNamespace(
            _busy=False, _validate_step=lambda: None, _error="", error_label=Control(),
            _progress_ok=True, _return_to_summary=True, _current="features",
            _show_step=Mock(),
        )
        setup.SetupPage._advance(obj)
        obj._show_step.assert_called_once_with("summary")
        self.assertFalse(obj._return_to_summary)

    def test_persona_creation_keeps_its_required_detail_step(self):
        obj = SimpleNamespace(
            _busy=False, _validate_step=lambda: None, _error="", error_label=Control(),
            _progress_ok=True, _return_to_summary=True, _current="persona", _persona_source="create",
            _show_step=Mock(),
        )
        setup.SetupPage._advance(obj)
        obj._show_step.assert_called_once_with("persona_create")
        self.assertTrue(obj._return_to_summary)

    def test_refresh_requires_discarding_existing_wizard_draft(self):
        obj = SimpleNamespace(_busy=False, _options={"loaded": True}, app=SimpleNamespace(window=None), refresh=Mock())
        with patch.object(setup.widgets, "ConfirmDialog") as dialog:
            setup.SetupPage.refresh_requested(obj)
        obj.refresh.assert_not_called()
        dialog.call_args.kwargs["on_confirm"]()
        obj.refresh.assert_called_once()

    def test_failed_submit_exposes_retry_and_preserves_payload(self):
        obj = SimpleNamespace(
            api=Mock(), _busy=False, _disposed=False, _validate_step=lambda: None,
            _set_error=Mock(), _set_busy=Mock(), status_label=Control(),
            _payload=lambda: {"providers": [{"api_key": "test-key"}]}, _submit=Mock(),
        )
        with patch.object(setup.widgets, "run_async") as runner:
            setup.SetupPage._submit(obj)
        runner.call_args.kwargs["on_error"](RuntimeError("offline"))
        self.assertIs(obj._set_error.call_args.args[1], obj._submit)
        self.assertIn("保留", obj._set_error.call_args.args[0])

    def test_disposed_setup_ignores_old_submit_response(self):
        obj = SimpleNamespace(
            api=Mock(), _busy=False, _disposed=False, _validate_step=lambda: None,
            _set_error=Mock(), _set_busy=Mock(), status_label=Control(),
            _payload=dict, _submit=Mock(), app=SimpleNamespace(on_setup_finished=Mock()), toast=Mock(),
        )
        with patch.object(setup.widgets, "run_async") as runner:
            setup.SetupPage._submit(obj)
        obj._disposed = True
        runner.call_args.kwargs["on_success"]({"ok": True})
        obj.app.on_setup_finished.assert_not_called()
        obj.toast.assert_not_called()


class BackupPanelContractTests(unittest.TestCase):
    def test_backup_poll_refreshes_live_category_progress(self):
        job = {
            "id": "backup-1", "state": "running", "total_bytes": 2048, "processed_bytes": 1024,
            "component_progress": {"workspace": {"estimated_bytes": 2048, "processed_bytes": 1024}},
        }
        panel = SimpleNamespace(
            page=SimpleNamespace(api=Mock()), _disposed=False, _active_job="backup-1",
            get_mapped=lambda: True, status_label=Control(), _render_jobs=Mock(),
            _schedule_poll=Mock(), refresh=Mock(),
        )
        panel.page.api.get.return_value = job
        with patch.object(settings_panels.widgets, "run_async",
                          lambda fn, on_success, on_error: on_success(fn())):
            settings_panels.BackupSettingsPanel._poll(panel)
        panel._render_jobs.assert_called_once_with([job])
        panel._schedule_poll.assert_called_once()

    def test_restore_poll_uses_restore_route_and_real_progress_contract(self):
        for state in ("running", "done", "failed"):
            with self.subTest(state=state):
                panel = SimpleNamespace(
                    page=SimpleNamespace(api=Mock(), toast=Mock()),
                    _disposed=False,
                    _restore_job="restore-1",
                    _restore_poll_source=1,
                    get_mapped=lambda: True,
                    status_label=Control(),
                    restore_status=Control(),
                    _restore_label=Control(),
                    _restore_progress_host=Control(),
                    _restore_button=Control(),
                    _restore_preview_button=Control(),
                    _restore_preview={"components": [
                        {"id": "config", "label": "配置", "archive_bytes": 2048},
                    ]},
                    _stop_restore_poll=Mock(),
                    _schedule_restore_poll=Mock(),
                    refresh=Mock(),
                )
                panel.page.api.get.return_value = {
                    "state": state, "stage": "restoring", "components": ["config"],
                    "progress": 1024, "total_bytes": 2048,
                    "component_progress": {"config": {"bytes": 1024, "files": 1}},
                    "rollback_filename": "rollback.zip",
                    "error": {"message": "write failed"} if state == "failed" else None,
                }
                with (
                    patch.object(settings_panels.widgets, "run_async",
                                 lambda fn, on_success, on_error: on_success(fn())),
                    patch.object(settings_panels.widgets, "clear"),
                    patch.object(settings_panels.widgets, "table") as table,
                ):
                    settings_panels.BackupSettingsPanel._poll_restore(panel)
                panel.page.api.get.assert_called_once_with(
                    "/api/backup/restore/jobs/restore-1", timeout=15,
                )
                self.assertEqual(table.call_args.args[1], [["配置", "1.0 KiB", "2.0 KiB"]])
                if state == "running":
                    self.assertIn("1.0 KiB / 2.0 KiB", panel.status_label.text)
                    panel._schedule_restore_poll.assert_called_once()
                    panel.refresh.assert_not_called()
                else:
                    self.assertEqual(panel._restore_job, "")
                    self.assertIn("rollback.zip", panel.status_label.text)
                    self.assertIn("rollback.zip", panel.restore_status.text)
                    self.assertIn("1.0 KiB", panel.restore_status.text)
                    panel._stop_restore_poll.assert_called_once()
                    panel.refresh.assert_called_once()

    def test_selected_size_ignores_unselected_unavailable_and_duplicate_rows(self):
        components = [
            {"id": "config", "bytes": 1024, "available": True},
            {"id": "chats", "bytes": 2048, "available": True},
            {"id": "credentials", "bytes": 8192, "available": False},
            {"id": "config", "bytes": 4096, "available": True},
        ]
        self.assertEqual(
            settings_panels._selected_backup_bytes(
                components, {"config", "credentials"}
            ),
            1024,
        )

    def test_selected_size_switches_workspace_media_estimate(self):
        components = [
            {
                "id": "workspace",
                "bytes": 500,
                "bytes_with_media": 5000,
                "bytes_without_media": 500,
                "available": True,
            }
        ]
        self.assertEqual(
            settings_panels._selected_backup_bytes(components, {"workspace"}),
            5000,
        )
        self.assertEqual(
            settings_panels._selected_backup_bytes(
                components, {"workspace"}, include_media=False
            ),
            500,
        )

    def test_media_choice_updates_rows_and_total_and_survives_refresh(self):
        class ActiveControl(Control):
            def __init__(self, active=True):
                super().__init__()
                self.active = active

            def get_active(self):
                return self.active

            def set_active(self, active):
                self.active = active

        panel = SimpleNamespace(
            _components_loaded=False,
            selected_components=set(),
            component_checks={},
            component_size_labels={},
            media_switch=ActiveControl(),
            component_size_label=Control(),
            start_button=Control(),
            component_box=Control(),
            _active_job="",
            _backup_starting=False,
            _restore_job="",
            _backup_running=False,
        )
        panel._component_toggled = lambda key, active: None
        panel._update_selected_size = lambda: settings_panels.BackupSettingsPanel._update_selected_size(panel)
        inventory = {
            "include_media": True,
            "components": [{
                "id": "workspace", "label": "工作区", "bytes": 5000,
                "bytes_with_media": 5000, "bytes_without_media": 500,
                "available": True,
            }],
        }
        with (
            patch.object(settings_panels.Gtk, "Box", lambda **kwargs: Control()),
            patch.object(settings_panels.Gtk.CheckButton, "new_with_label", lambda text: ActiveControl()),
            patch.object(settings_panels.widgets, "clear", lambda box: box.children.clear()),
            patch.object(settings_panels.widgets, "label", lambda text: Control(text)),
        ):
            settings_panels.BackupSettingsPanel._render_components(panel, inventory)
            self.assertEqual(panel.component_size_labels["workspace"].text, "4.9 KiB")
            panel.media_switch.set_active(False)
            panel._update_selected_size()
            self.assertEqual(panel.component_size_labels["workspace"].text, "500 B")
            self.assertIn("500 B", panel.component_size_label.text)
            settings_panels.BackupSettingsPanel._render_components(panel, inventory)
        self.assertFalse(panel.media_switch.get_active())
        self.assertEqual(panel.component_size_labels["workspace"].text, "500 B")

    def preview(self, **updates):
        return {
            "ok": True,
            "filename": "backup.zip",
            "confirmation_phrase": "恢复备份",
            "components": [
                {"id": "config", "available": True, "restorable": True},
                {"id": "chats", "available": True, "restorable": True},
                {"id": "credentials", "available": False, "restorable": False},
            ],
            **updates,
        }

    def test_restore_payload_requires_exact_preview_selection_and_phrase(self):
        preview = self.preview()
        payload = settings_panels._restore_payload(
            "backup.zip", {"config", "chats"}, preview, "恢复备份"
        )
        self.assertEqual(payload, {
            "filename": "backup.zip",
            "components": ["chats", "config"],
            "confirmation": "恢复备份",
        })
        for selected, phrase in [
            ({"config"}, "恢复备份"),
            ({"config", "chats"}, "恢复"),
            ({"config", "credentials"}, "恢复备份"),
        ]:
            with (
                self.subTest(selected=selected, phrase=phrase),
                self.assertRaises(ValueError),
            ):
                settings_panels._restore_payload(
                    "backup.zip", selected, preview, phrase
                )

    def test_restore_payload_rejects_a_preview_for_another_backup(self):
        with self.assertRaisesRegex(ValueError, "备份文件已变化"):
            settings_panels._restore_payload(
                "other.zip", {"config", "chats"}, self.preview(), "恢复备份"
            )

    def test_restore_payload_requires_preview_before_submission(self):
        with self.assertRaisesRegex(ValueError, "先预览"):
            settings_panels._restore_payload(
                "backup.zip", {"config"}, None, "恢复备份"
            )

    def test_backup_request_contains_only_selected_components_and_media_choice(self):
        panel = SimpleNamespace(
            page=SimpleNamespace(api=Mock(), toast=Mock()),
            _disposed=False,
            selected_components={"config", "chats"},
            media_switch=SimpleNamespace(get_active=lambda: False),
            start_button=Control(),
            status_label=Control(),
            refresh=Mock(),
        )
        panel.page.api.post.return_value = {"message": "started"}
        with patch.object(
            settings_panels.widgets,
            "run_async",
            lambda fn, on_success, on_error: on_success(fn()),
        ):
            settings_panels.BackupSettingsPanel._start(panel)
        args, kwargs = panel.page.api.post.call_args
        self.assertEqual(args[:2], (
            "/api/backup",
            {"components": ["chats", "config"], "include_media": False},
        ))
        self.assertEqual(kwargs, {"timeout": 60})
        panel.refresh.assert_called_once()

    def test_empty_backup_selection_does_not_start_a_job(self):
        panel = SimpleNamespace(
            page=SimpleNamespace(api=Mock()),
            _disposed=False,
            selected_components=set(),
            status_label=Control(),
            start_button=Control(),
        )
        settings_panels.BackupSettingsPanel._start(panel)
        panel.page.api.post.assert_not_called()
        self.assertIn("至少选择一类", panel.status_label.text)

    def test_pending_backup_creation_blocks_duplicate_submission(self):
        panel = SimpleNamespace(
            page=SimpleNamespace(api=Mock(), toast=Mock()),
            _disposed=False,
            _backup_starting=False,
            selected_components={"config"},
            media_switch=SimpleNamespace(get_active=lambda: True),
            start_button=Control(),
            status_label=Control(),
            refresh=Mock(),
        )
        with patch.object(settings_panels.widgets, "run_async") as runner:
            settings_panels.BackupSettingsPanel._start(panel)
            settings_panels.BackupSettingsPanel._start(panel)
        self.assertEqual(runner.call_count, 1)
        self.assertTrue(panel._backup_starting)
        runner.call_args.kwargs["on_error"](RuntimeError("failed"))
        self.assertFalse(panel._backup_starting)


if __name__ == "__main__":
    unittest.main()

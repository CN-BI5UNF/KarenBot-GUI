"""AI persona generation, refinement and direct prompt editing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import widgets  # noqa: E402
from ..api import q  # noqa: E402

BRIEF_FIELDS = [
    (
        "personality",
        "这个人格是什么样的人",
        "话多话少、急性子慢性子、有什么小怪癖、对什么人什么态度。",
    ),
    (
        "background",
        "过往",
        "从哪儿来，做过什么；帮你理解 ta 是谁就够了。",
    ),
    (
        "voice_samples",
        "说话的样子",
        "贴几句 ta 常说的话，比如「嗯」「可以的」「我想一下」。",
    ),
    (
        "boundaries",
        "不会做的事",
        "ta 不做什么、不接受什么；几句话划定边界。",
    ),
    (
        "never_say",
        "绝不会说的话",
        "比会说什么更能定义一个人，比如绝不叫别人宝贝。",
    ),
    (
        "relation_matrix",
        "对不同人，有什么差别",
        "对死党和对长辈是两种语气；不写 AI 也能推导。",
    ),
    (
        "sensitive_topics",
        "什么话题会让 ta 沉默或岔开",
        "有没有一提就躲的事，可以不填。",
    ),
    (
        "extra_notes",
        "还有什么要补充的",
        "比如「别写成客服」「少说教」。",
    ),
]


def _shell(
    page: Any,
    title_text: str,
    *,
    width: int = 840,
    height: int = 760,
) -> tuple[Gtk.Window, Gtk.Box, Gtk.Box, Gtk.Box]:
    window = Gtk.Window()
    window.set_title(title_text)
    window.set_default_size(width, height)
    window.set_transient_for(page.app.window)
    window.set_modal(True)
    header = Adw.HeaderBar()
    window.set_titlebar(header)
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    scroller = Gtk.ScrolledWindow()
    scroller.set_vexpand(True)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    body.set_margin_top(16)
    body.set_margin_bottom(16)
    body.set_margin_start(18)
    body.set_margin_end(18)
    scroller.set_child(body)
    outer.append(scroller)
    footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    footer.set_margin_top(8)
    footer.set_margin_bottom(12)
    footer.set_margin_start(18)
    footer.set_margin_end(18)
    outer.append(footer)
    window.set_child(outer)
    return window, body, footer, scroller


def _field(label_text: str, control: Gtk.Widget, help_text: str = "") -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.append(widgets.label(label_text, css="field-label"))
    if help_text:
        box.append(widgets.muted(help_text))
    box.append(control)
    return box


def _text_area(initial: str = "", *, height: int = 80, monospace: bool = False) -> Gtk.ScrolledWindow:
    return widgets.text_view(initial, height=height, monospace=monospace)


def _status_label() -> Gtk.Label:
    label = widgets.muted("")
    label.set_hexpand(True)
    return label


def open_ai_creator(page: Any, on_done: Any) -> None:
    """Open the AI creator, importing a stashed setup-wizard brief if present."""

    def _load_brief() -> dict[str, Any] | None:
        try:
            data = page.api.get("/api/personas/brief", timeout=30)
            brief = data.get("brief")
            if brief:
                page.api.delete("/api/personas/brief", timeout=30)
            return brief
        except BaseException:  # noqa: BLE001
            return None

    widgets.run_async(
        _load_brief,
        on_success=lambda brief: _show_creator(page, on_done, brief),
        on_error=lambda _exc: _show_creator(page, on_done, None),
    )


def _show_creator(page: Any, on_done: Any, stashed: dict[str, Any] | None) -> None:
    window, body, footer, _scroller = _shell(page, "新建人格 · AI 生成", height=820)
    status = _status_label()
    state: dict[str, Any] = {"xml": "", "busy": False}

    name_entry = Gtk.Entry()
    name_entry.set_placeholder_text("linwan（目录名，字母或中文开头）")
    display_name = Gtk.Entry()
    display_name.set_placeholder_text("林晚（人格自称）")
    name_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    name_row.set_homogeneous(True)
    name_row.append(_field("人格目录名", name_entry, "它会成为 personas/ 下的目录名"))
    name_row.append(_field("显示名", display_name, "人格自称的名字，可以中文"))
    body.append(name_row)
    body.append(
        widgets.muted(
            "写几句你想要的人格的样子，AI 会补成完整人设。生成后可以反复重写，"
            "满意了再采用；生成过程不会写盘。"
        )
    )

    brief_views: dict[str, Gtk.ScrolledWindow] = {}
    for key, label_text, help_text in BRIEF_FIELDS:
        area = _text_area(height=64)
        brief_views[key] = area
        body.append(_field(label_text, area, help_text))

    preview_title = widgets.label("生成预览", css="section-title")
    preview_title.set_visible(False)
    preview = _text_area(height=300, monospace=True)
    preview.set_visible(False)
    body.append(preview_title)
    body.append(preview)

    if stashed:
        personality = brief_views["personality"]
        buffer = personality.text_view.get_buffer()  # type: ignore[attr-defined]
        buffer.set_text(str(stashed.get("personality") or ""))
        display_name.set_text(str(stashed.get("name") or ""))
        status.set_text("已带入首次配置里写的人格描述；补个目录名就能生成。")

    cancel = widgets.button("取消")
    cancel.connect("clicked", lambda _b: window.close())
    generate = widgets.button("生成草稿", css="suggested-action")
    adopt = widgets.button("采用并保存", css="suggested-action")
    adopt.set_visible(False)
    footer.append(status)
    footer.append(cancel)
    footer.append(generate)
    footer.append(adopt)

    def set_busy(busy: bool) -> None:
        state["busy"] = busy
        generate.set_sensitive(not busy)
        adopt.set_sensitive(not busy)

    def collect_brief() -> dict[str, Any]:
        brief: dict[str, Any] = {
            "name": display_name.get_text().strip() or name_entry.get_text().strip(),
            "admins": [],
        }
        for key, _label, _help in BRIEF_FIELDS:
            brief[key] = widgets.text_value(brief_views[key]).strip()
        return brief

    def generate_draft() -> None:
        if state["busy"]:
            return
        name = name_entry.get_text().strip()
        if not name:
            status.set_text("先给人格起个目录名。")
            return
        if not re.match(r"^[A-Za-z0-9一-鿿][A-Za-z0-9_.\-一-鿿]{0,63}$", name):
            status.set_text("目录名只能包含字母、数字、中文、下划线、点和短横线。")
            return
        set_busy(True)
        status.set_text("正在生成，大概要十几秒…")

        def _do() -> dict[str, Any]:
            return page.api.post("/api/personas/draft", collect_brief(), timeout=180)

        def _done(result: dict[str, Any]) -> None:
            state["xml"] = str(result.get("xml") or "")
            buffer = preview.text_view.get_buffer()  # type: ignore[attr-defined]
            buffer.set_text(state["xml"])
            preview_title.set_visible(True)
            preview.set_visible(True)
            adopt.set_visible(True)
            status.set_text("已生成。不满意就改改描述再点一次，满意后采用。")
            set_busy(False)

        def _failed(exc: BaseException) -> None:
            status.set_text(f"生成失败：{exc}")
            set_busy(False)

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def save_draft(overwrite: bool = False) -> None:
        if not state["xml"] or state["busy"]:
            return
        name = name_entry.get_text().strip()
        brief = collect_brief()
        brief.pop("name", None)
        payload = {
            "name": name,
            "xml": state["xml"],
            "overwrite": overwrite,
            "display_name": display_name.get_text().strip() or name,
            **brief,
        }
        set_busy(True)
        status.set_text("正在保存…")

        def _do() -> dict[str, Any]:
            return page.api.post("/api/personas", payload, timeout=60)

        def _done(result: dict[str, Any]) -> None:
            page.toast(str(result.get("message") or "人格已创建"))
            if result.get("backup"):
                page.toast(f"原人设已备份到 {result['backup']}")
            window.close()
            on_done()

        def _failed(exc: BaseException) -> None:
            if not overwrite and "已存在" in str(exc):
                set_busy(False)
                widgets.ConfirmDialog(
                    page.app.window,
                    heading="同名人格已存在",
                    body=f"{exc}\n\n覆盖前会自动备份。",
                    confirm_label="覆盖",
                    destructive=True,
                    on_confirm=lambda: save_draft(True),
                )
                return
            status.set_text(f"保存失败：{exc}")
            set_busy(False)

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    generate.connect("clicked", lambda _b: generate_draft())
    adopt.connect("clicked", lambda _b: save_draft(False))
    window.present()
    name_entry.grab_focus()


def open_direct_editor(page: Any, name: str | None, on_done: Any) -> None:
    editing = bool(name)
    window, body, footer, _scroller = _shell(
        page,
        f"编辑 {name}" if editing else "直接写提示词",
        height=820,
    )
    status = _status_label()

    name_entry = Gtk.Entry()
    name_entry.set_text(name or "")
    name_entry.set_placeholder_text("xiaowan（目录名）")
    name_entry.set_sensitive(not editing)
    display_name = Gtk.Entry()
    display_name.set_placeholder_text("小晚（人格自称，留空使用目录名）")
    gender = Gtk.Entry()
    gender.set_placeholder_text("female / male / 其他（可选）")
    age = Gtk.Entry()
    age.set_placeholder_text("可选，0–1000")
    admin_qq = Gtk.Entry()
    admin_qq.set_placeholder_text("管理员 QQ（可选）")
    admin_name = Gtk.Entry()
    admin_name.set_placeholder_text("管理员称呼（可选）")
    prompt = _text_area(height=360)
    prompt.set_vexpand(True)
    counter = widgets.muted("0 / 20000 字符")

    name_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    name_row.set_homogeneous(True)
    name_row.append(_field("人格目录名", name_entry, "编辑时不可改目录名；要改名请用复制"))
    name_row.append(_field("显示名", display_name))
    body.append(name_row)
    details = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    details.set_homogeneous(True)
    details.append(_field("性别", gender))
    details.append(_field("年龄", age))
    body.append(details)
    admins = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    admins.set_homogeneous(True)
    admins.append(_field("管理员 QQ", admin_qq))
    admins.append(_field("管理员称呼", admin_name))
    body.append(admins)
    body.append(
        _field(
            "人格提示词",
            prompt,
            "写“你是谁、怎么说话、性格、边界、示例”即可；工具用法和分条规则由系统负责。",
        )
    )
    body.append(counter)

    view: Gtk.TextView = prompt.text_view  # type: ignore[attr-defined]
    buffer = view.get_buffer()

    def update_counter(*_args: Any) -> None:
        length = len(widgets.text_value(prompt))
        counter.set_text(f"{length} / 20000 字符")
        counter.remove_css_class("danger-text")
        if length > 20000:
            counter.add_css_class("danger-text")

    buffer.connect("changed", update_counter)
    update_counter()

    cancel = widgets.button("取消")
    cancel.connect("clicked", lambda _b: window.close())
    save_button = widgets.button("保存覆盖" if editing else "保存人格", css="suggested-action")
    footer.append(status)
    footer.append(cancel)
    footer.append(save_button)

    def save(overwrite: bool = editing) -> None:
        if page.api is None:
            return
        target = name_entry.get_text().strip()
        content = widgets.text_value(prompt)
        if not target:
            status.set_text("先填人格目录名。")
            return
        if not content.strip():
            status.set_text("提示词不能为空。")
            return
        if len(content) > 20000:
            status.set_text("提示词超过 20000 字符。")
            return
        admin_entries = []
        if admin_qq.get_text().strip():
            admin_entries.append(
                {
                    "qq": admin_qq.get_text().strip(),
                    "name": admin_name.get_text().strip(),
                    "role": "owner",
                }
            )
        payload = {
            "name": target,
            "xml": content,
            "raw": True,
            "overwrite": overwrite,
            "display_name": display_name.get_text().strip(),
            "gender": gender.get_text().strip(),
            "age": age.get_text().strip() or None,
            "admins": admin_entries,
        }
        save_button.set_sensitive(False)
        status.set_text("正在保存…")

        def _do() -> dict[str, Any]:
            return page.api.post("/api/personas", payload, timeout=60)

        def _done(result: dict[str, Any]) -> None:
            page.toast(str(result.get("message") or "人格已保存"))
            if result.get("backup"):
                page.toast(f"原人设已备份到 {result['backup']}")
            window.close()
            on_done()

        def _failed(exc: BaseException) -> None:
            if not overwrite and "已存在" in str(exc):
                save_button.set_sensitive(True)
                widgets.ConfirmDialog(
                    page.app.window,
                    heading="同名人格已存在",
                    body=f"{exc}\n\n覆盖前会自动备份。",
                    confirm_label="覆盖",
                    destructive=True,
                    on_confirm=lambda: save(True),
                )
                return
            status.set_text(f"保存失败：{exc}")
            save_button.set_sensitive(True)

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    save_button.connect("clicked", lambda _b: save(editing))
    window.present()
    prompt.grab_focus()

    if editing:
        status.set_text("正在读取当前提示词…")

        def _load() -> dict[str, Any]:
            return page.api.get(f"/api/personas/{q(name)}/source", timeout=30)

        def _loaded(data: dict[str, Any]) -> None:
            buffer.set_text(str(data.get("xml") or ""))
            values = data.get("vars") or {}
            display_name.set_text(str(values.get("name") or ""))
            gender.set_text(str(values.get("gender") or ""))
            value_age = values.get("age")
            age.set_text("" if value_age in (None, "") else str(value_age))
            admin = (values.get("admins") or [None])[0]
            if isinstance(admin, dict):
                admin_qq.set_text(str(admin.get("qq") or ""))
                admin_name.set_text(str(admin.get("name") or ""))
            status.set_text("已读取当前提示词；保存覆盖前会自动备份。")

        widgets.run_async(_load, on_success=_loaded, on_error=lambda exc: status.set_text(str(exc)))


def open_refiner(page: Any, name: str, on_done: Any) -> None:
    window, body, footer, _scroller = _shell(page, f"AI 改写 · {name}", height=800)
    status = _status_label()
    state: dict[str, Any] = {"xml": "", "refined": 0, "history": [], "busy": False}

    feedback = _text_area(height=90)
    preview_title = widgets.label("修改版预览", css="section-title")
    preview_title.set_visible(False)
    preview = _text_area(height=340, monospace=True)
    preview.set_visible(False)
    body.append(
        widgets.muted(
            "贴一句想改的地方，AI 会出一版修改稿。确认前不会动现有文件；"
            "采用时会自动备份旧人设。"
        )
    )
    body.append(_field("想改哪里", feedback, "比如「再冷淡一点」「少说反问句」"))
    body.append(preview_title)
    body.append(preview)

    cancel = widgets.button("取消")
    cancel.connect("clicked", lambda _b: window.close())
    generate = widgets.button("生成修改版", css="suggested-action")
    generate.set_sensitive(False)
    adopt = widgets.button("采用并覆盖", css="destructive-action")
    adopt.set_visible(False)
    footer.append(status)
    footer.append(cancel)
    footer.append(generate)
    footer.append(adopt)

    def set_busy(busy: bool) -> None:
        state["busy"] = busy
        generate.set_sensitive(not busy and bool(state["xml"]))
        adopt.set_sensitive(not busy)

    def generate_draft() -> None:
        text = widgets.text_value(feedback).strip()
        if not text:
            status.set_text("先说说想改哪里。")
            return
        if state["busy"] or not state["xml"]:
            return
        set_busy(True)
        status.set_text(f"正在生成修改版（第 {state['refined'] + 1} 版）…")

        def _do() -> dict[str, Any]:
            return page.api.post(
                "/api/personas/refine",
                {
                    "xml": state["xml"],
                    "feedback": text,
                    "refined_count": state["refined"],
                    "edit_history": state["history"],
                },
                timeout=180,
            )

        def _done(result: dict[str, Any]) -> None:
            state["xml"] = str(result.get("xml") or state["xml"])
            state["refined"] = int(result.get("refined_count") or state["refined"] + 1)
            state["history"].append({"role": "user", "content": text})
            state["history"].append({"role": "assistant", "content": state["xml"]})
            buffer = preview.text_view.get_buffer()  # type: ignore[attr-defined]
            buffer.set_text(state["xml"])
            preview_title.set_text(f"修改版（第 {state['refined']} 版）")
            preview_title.set_visible(True)
            preview.set_visible(True)
            adopt.set_visible(True)
            feedback_buffer = feedback.text_view.get_buffer()  # type: ignore[attr-defined]
            feedback_buffer.set_text("")
            status.set_text("修改版已生成。确认后会覆盖当前人设。")
            set_busy(False)

        def _failed(exc: BaseException) -> None:
            status.set_text(f"改写失败：{exc}")
            set_busy(False)

        widgets.run_async(_do, on_success=_done, on_error=_failed)

    def accept() -> None:
        if not state["xml"] or state["busy"]:
            return

        def _do_save() -> None:
            set_busy(True)
            status.set_text("正在保存…")

            def _do() -> dict[str, Any]:
                return page.api.post(
                    "/api/personas",
                    {
                        "name": name,
                        "xml": state["xml"],
                        "overwrite": True,
                    },
                    timeout=60,
                )

            def _done(result: dict[str, Any]) -> None:
                page.toast(str(result.get("message") or "人格已更新"))
                if result.get("backup"):
                    page.toast(f"原人设已备份到 {result['backup']}")
                window.close()
                on_done()

            def _failed(exc: BaseException) -> None:
                status.set_text(f"保存失败：{exc}")
                set_busy(False)

            widgets.run_async(_do, on_success=_done, on_error=_failed)

        widgets.ConfirmDialog(
            page.app.window,
            heading=f"覆盖 {name} 的人设？",
            body="覆盖前会自动备份到 personas/<name>/.backups/。",
            confirm_label="采用并覆盖",
            destructive=True,
            on_confirm=_do_save,
        )

    generate.connect("clicked", lambda _b: generate_draft())
    adopt.connect("clicked", lambda _b: accept())
    status.set_text("正在读取当前人设…")

    def _load() -> dict[str, Any]:
        return page.api.get(f"/api/personas/{q(name)}/source", timeout=30)

    def _loaded(data: dict[str, Any]) -> None:
        state["xml"] = str(data.get("xml") or "")
        status.set_text("已读取当前人设。写一句想改的地方，点「生成修改版」。")
        set_busy(False)

    def _failed(exc: BaseException) -> None:
        status.set_text(f"读取失败：{exc}")

    widgets.run_async(_load, on_success=_loaded, on_error=_failed)
    window.present()
    view: Gtk.TextView = feedback.text_view  # type: ignore[attr-defined]
    view.grab_focus()


def export_persona(page: Any, name: str) -> None:
    if page.api is None:
        return
    target = widgets.save_path_picker(
        page.app.window,
        title_text=f"导出 {name}",
        initial_name=f"{name}.zip",
    )
    if not target:
        return

    def _do() -> int:
        data = page.api.raw(f"/api/personas/{q(name)}/export", timeout=300)
        path = Path(target)
        path.write_bytes(data)
        return len(data)

    widgets.run_async(
        _do,
        on_success=lambda size: page.toast(
            f"已导出 {name}（{widgets.format_bytes(size)}）"
        ),
        on_error=lambda exc: page.toast(f"导出失败：{exc}"),
    )

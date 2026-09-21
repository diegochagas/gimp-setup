#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GIMP AI Plugin

Vendored from lukaso/gimp-ai (v0.14.0, MIT licensed, (c) 2025 Lukas
Oberhuber; see LICENSE). This gimp-setup edition runs Generative Fill and
Image Generator only on the two fully local ComfyUI models (FLUX.2 klein
and Qwen-Image-Edit); see ai_providers.py and PATCHES.md.
"""

VERSION = "0.14.0"

import sys
import os
import gi
import json
import base64
import tempfile

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gegl", "0.4")
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gimp, GimpUi, GLib, Gegl, Gio, Gtk, Gdk

# Import pure coordinate transformation functions
from coordinate_utils import (
    calculate_mask_coordinates,
    calculate_placement_coordinates,
    validate_context_info,
    get_optimal_openai_shape as get_optimal_shape,  # upstream's name
    calculate_padding_for_shape,
    extract_context_with_selection,
    calculate_result_placement,
    calculate_scale_from_shape,
)

# gimp-setup patch: the local ComfyUI backends (FLUX.2 klein and
# Qwen-Image-Edit) live in ai_providers.py next to this file.
import ai_providers


# gimp-setup patch: config keys written by earlier versions for features
# that were removed (online providers, which can hold an API key, and a
# removed dialog's state). They are dropped on load, so they are never
# written back.
_LEGACY_CONFIG_KEYS = ("openai", "gemini", "sdwebui", "last_use_mask")


class GimpAIPlugin(Gimp.PlugIn):
    """Simplified AI Plugin"""

    def __init__(self):
        super().__init__()
        self.config = self._load_config()
        self._cancel_requested = False

    def _load_config(self):
        """Load configuration from various locations"""
        # Use GIMP API for primary config location
        try:
            plugin_dir = Gimp.PlugIn.directory()
            gimp_config_path = os.path.join(plugin_dir, "gimp-ai-plugin", "config.json")
        except:
            gimp_config_path = None

        config_paths = []

        # Try GIMP preferences directory first (where we want to save)
        try:
            gimp_user_dir = Gimp.directory()
            gimp_prefs_path = os.path.join(
                gimp_user_dir, "gimp-ai-plugin", "config.json"
            )
            config_paths.append(gimp_prefs_path)
        except:
            pass

        # Then try user config directory (migration path)
        config_paths.append(os.path.expanduser("~/.config/gimp-ai/config.json"))

        # Then try GIMP plugin directory
        if gimp_config_path:
            config_paths.append(gimp_config_path)

        # Fallback paths for backward compatibility
        config_paths.extend(
            [
                os.path.join(os.path.dirname(__file__), "config.json"),
                os.path.expanduser("~/.gimp-ai-config.json"),
            ]
        )

        for config_path in config_paths:
            try:
                if os.path.exists(config_path):
                    with open(config_path, "r") as f:
                        config = json.load(f)
                        print(f"DEBUG: Loaded config from {config_path}")
                        return self._clean_config(config)
            except Exception as e:
                print(f"DEBUG: Failed to load config from {config_path}: {e}")
                continue

        # Default config with prompt history support
        print("DEBUG: Using default config (no config file found)")
        return {
            "provider": ai_providers.DEFAULT_PROVIDER,
            "settings": {"max_image_size": 512, "timeout": 30},
            "prompt_history": [],
            "last_prompt": "",
        }

    def _clean_config(self, config):
        """gimp-setup patch: drop legacy sections (which may hold an API key)
        and map a saved provider that no longer exists to the default."""
        if not isinstance(config, dict):
            config = {}
        for key in _LEGACY_CONFIG_KEYS:
            config.pop(key, None)
        config["provider"] = ai_providers.normalize_provider(config.get("provider"))
        return config

    def _save_config(self):
        """Save configuration to GIMP preferences directory"""
        try:
            # Use GIMP's user directory (where preferences are stored)
            gimp_user_dir = Gimp.directory()
            config_dir = os.path.join(gimp_user_dir, "gimp-ai-plugin")
            config_path = os.path.join(config_dir, "config.json")

            # Create directory if it doesn't exist
            os.makedirs(config_dir, exist_ok=True)

            with open(config_path, "w") as f:
                json.dump(self._clean_config(self.config), f, indent=4)
            print(f"DEBUG: Saved config to GIMP preferences: {config_path}")
            return True
        except Exception as e:
            print(f"DEBUG: Failed to save config to GIMP preferences: {e}")
            # Fallback to user config directory
            try:
                config_dir = os.path.expanduser("~/.config/gimp-ai")
                config_path = os.path.join(config_dir, "config.json")
                os.makedirs(config_dir, exist_ok=True)
                with open(config_path, "w") as f:
                    json.dump(self._clean_config(self.config), f, indent=4)
                print(f"DEBUG: Saved config to fallback location: {config_path}")
                return True
            except Exception as e2:
                print(f"DEBUG: All config save attempts failed: {e2}")
                return False

    def _add_to_prompt_history(self, prompt):
        """Add prompt to history, keeping last 10 unique prompts"""
        if not prompt.strip():
            return

        # Remove if already exists to avoid duplicates
        history = self.config.get("prompt_history", [])
        if prompt in history:
            history.remove(prompt)

        # Add to beginning
        history.insert(0, prompt)

        # Keep only last 10
        history = history[:10]

        self.config["prompt_history"] = history
        self.config["last_prompt"] = prompt
        self._save_config()

    def _get_prompt_history(self):
        """Get prompt history list"""
        return self.config.get("prompt_history", [])

    def _get_last_prompt(self):
        """Get the last used prompt"""
        return self.config.get("last_prompt", "")

    def _get_provider(self):
        """Active local model: an ai_providers.PROVIDERS id (default comfyui-klein)."""
        return ai_providers.normalize_provider((self.config or {}).get("provider"))

    def _get_processing_mode(self, dialog_mode=None):
        """Determine processing mode based on dialog selection or fallback to config"""
        if dialog_mode:
            return dialog_mode

        # Fallback to last used mode from config
        return self.config.get("last_mode", "contextual")

    def _update_progress(self, progress_label, message, gimp_progress=None):
        """Update progress message in dialog with proper emoji encoding, optionally update GIMP progress bar"""
        if progress_label:
            try:
                # Ensure the message is properly encoded for GTK
                # GTK should handle UTF-8 properly, but let's be explicit
                if isinstance(message, str):
                    encoded_message = message.encode("utf-8").decode("utf-8")
                else:
                    encoded_message = str(message)

                # Use GLib.idle_add to ensure the update happens on the main thread
                def update_ui():
                    try:
                        print(
                            f"DEBUG: Actually updating progress label to: {encoded_message}"
                        )
                        progress_label.set_text(encoded_message)
                        progress_label.set_use_markup(
                            False
                        )  # Use plain text, not markup
                        print(
                            f"DEBUG: Progress label text is now: {progress_label.get_text()}"
                        )
                        return False  # Remove from idle queue after running once
                    except Exception as e:
                        print(f"DEBUG: UI update failed: {e}")
                        return False

                # Queue the update on the main thread
                GLib.idle_add(update_ui)

            except Exception as e:
                print(f"DEBUG: Progress update failed: {e}")
                # Fallback without emojis if there's encoding issue
                fallback = (
                    message.encode("ascii", "ignore").decode("ascii")
                    if message
                    else "Processing..."
                )
                try:
                    progress_label.set_text(fallback)
                except:
                    pass

        # Update GIMP progress bar if fraction provided
        if gimp_progress is not None:
            try:
                Gimp.progress_set_text(message)
                Gimp.progress_update(gimp_progress)
                Gimp.displays_flush()
            except:
                pass  # Ignore if not in right context

        return False  # Return False for GLib.idle_add compatibility

    def _create_progress_callback(self, progress_label):
        """Create a reusable progress callback for threading"""

        def progress_callback(message):
            def update_ui():
                self._update_progress(progress_label, message)
                return False

            GLib.idle_add(update_ui)

        return progress_callback

    def _create_progress_widget(self):
        """Create progress label widget for dialogs"""
        progress_label = Gtk.Label()
        progress_label.set_text("Ready to start...")
        return progress_label, progress_label

    def _init_gimp_ui(self):
        """Initialize GIMP UI system if not already done"""
        if not hasattr(self, "_ui_initialized"):
            GimpUi.init("gimp-ai-plugin")
            self._ui_initialized = True

    def _create_dialog_base(self, title="Dialog", size=(500, 400)):
        """Create a standard GIMP dialog with consistent styling"""
        self._init_gimp_ui()

        # Create dialog with header bar detection
        use_header_bar = Gtk.Settings.get_default().get_property(
            "gtk-dialogs-use-header"
        )
        dialog = GimpUi.Dialog(use_header_bar=use_header_bar, title=title)

        # Set up dialog properties
        dialog.set_default_size(size[0], size[1])
        dialog.set_resizable(True)

        return dialog

    def _setup_dialog_content_area(self, dialog, spacing=15, margin=20):
        """Set up dialog content area with consistent styling"""
        content_area = dialog.get_content_area()
        content_area.set_spacing(spacing)
        content_area.set_margin_start(margin)
        content_area.set_margin_end(margin)
        content_area.set_margin_top(margin)
        content_area.set_margin_bottom(margin)
        return content_area

    def _is_debug_mode(self):
        """Check if debug mode is enabled (saves temp files to system temp directory)"""
        # Check config first
        debug = self.config.get("debug_mode", False)
        # Allow environment variable override
        if os.environ.get("GIMP_AI_DEBUG") == "1":
            debug = True
        return debug

    def _check_cancel_and_process_events(self):
        """Check if cancel was requested and process minimal UI events"""
        # Process GTK events more aggressively for better UI responsiveness
        try:
            # Process multiple pending events to improve responsiveness
            if hasattr(Gtk, "events_pending"):
                event_count = 0
                while (
                    Gtk.events_pending() and event_count < 5
                ):  # Process up to 5 events
                    Gtk.main_iteration_do(False)  # Non-blocking iteration
                    event_count += 1
        except Exception as e:
            print(f"DEBUG: GTK event processing warning (non-fatal): {e}")

        return self._cancel_requested

    def _show_prompt_dialog(
        self, title="AI Prompt", default_text="", show_mode_selection=True, image=None
    ):
        """Show a GIMP UI dialog to get user input for AI prompt"""
        # Use last prompt as default if available, otherwise use provided default
        if not default_text:
            default_text = self._get_last_prompt()
        if not default_text:
            if title == "Generative Fill":
                default_text = "Describe what to fill the selection with (e.g. 'remove object', 'a wooden fence')"
            else:
                default_text = "Describe what you want to generate..."
        try:
            # Create dialog using helper methods
            dialog = self._create_dialog_base(title, (600, 300))

            # Add buttons using GIMP's standard approach
            dialog.add_button(
                "Settings", Gtk.ResponseType.HELP
            )  # Use HELP for Settings
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            ok_button = dialog.add_button("OK", Gtk.ResponseType.OK)
            ok_button.set_can_default(True)
            ok_button.grab_default()

            # Set up content area using helper
            content_area = self._setup_dialog_content_area(dialog, spacing=10)

            # Label - will automatically use theme colors
            label = Gtk.Label(label="Enter your AI prompt:")
            label.set_halign(Gtk.Align.START)
            content_area.pack_start(label, False, False, 0)

            # Prompt history dropdown
            history = self._get_prompt_history()
            history_combo = None
            if history:
                history_label = Gtk.Label(label="Recent prompts:")
                history_label.set_halign(Gtk.Align.START)
                content_area.pack_start(history_label, False, False, 0)

                history_combo = Gtk.ComboBoxText()
                history_combo.append_text("Select from recent prompts...")
                for prompt in history:
                    # Truncate long prompts for display
                    display_prompt = prompt[:60] + "..." if len(prompt) > 60 else prompt
                    history_combo.append_text(display_prompt)
                history_combo.set_active(0)
                content_area.pack_start(history_combo, False, False, 0)

            # Multiline text view for prompts
            scrolled_window = Gtk.ScrolledWindow()
            scrolled_window.set_policy(
                Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
            )
            scrolled_window.set_size_request(560, 150)

            text_view = Gtk.TextView()
            text_view.set_wrap_mode(Gtk.WrapMode.WORD)
            text_view.set_border_width(8)

            # Set default text
            text_buffer = text_view.get_buffer()
            text_buffer.set_text(default_text)

            scrolled_window.add(text_view)
            content_area.pack_start(scrolled_window, True, True, 0)

            # Add mode selection (only for inpainting)
            focused_radio = None
            full_radio = None
            if show_mode_selection:
                mode_frame = Gtk.Frame(label="Processing Mode:")
                mode_frame.set_margin_top(10)
                content_area.pack_start(mode_frame, False, False, 0)

                mode_box = Gtk.VBox()
                mode_box.set_margin_start(10)
                mode_box.set_margin_end(10)
                mode_box.set_margin_top(5)
                mode_box.set_margin_bottom(10)
                mode_frame.add(mode_box)

                # Get last used mode from config
                config = self._load_config()
                last_mode = config.get("last_mode", "contextual")

                # Radio buttons for mode selection
                focused_radio = Gtk.RadioButton.new_with_label(
                    None,
                    "Focused (High Detail) - Best for small edits, maximum resolution",
                )
                focused_radio.set_name("contextual")
                mode_box.pack_start(focused_radio, False, False, 2)

                full_radio = Gtk.RadioButton.new_with_label_from_widget(
                    focused_radio,
                    "Full Image (Consistent) - Best for large changes, visual consistency",
                )
                full_radio.set_name("full_image")
                mode_box.pack_start(full_radio, False, False, 2)

                # Set active radio based on last used mode
                if last_mode == "full_image":
                    full_radio.set_active(True)
                else:
                    focused_radio.set_active(True)

            # Connect Enter to activate OK button, Shift+Enter for new line
            def on_key_press(widget, event):
                if event.keyval == Gdk.KEY_Return:
                    # Shift+Enter: Allow new line (default behavior)
                    if event.state & Gdk.ModifierType.SHIFT_MASK:
                        return False  # Let default behavior handle it
                    # Plain Enter or Ctrl+Enter: Submit dialog
                    else:
                        dialog.response(Gtk.ResponseType.OK)
                        return True
                return False

            text_view.connect("key-press-event", on_key_press)

            # Connect history selection to populate text view
            if history_combo:

                def on_history_changed(combo):
                    active = combo.get_active()
                    if active > 0:  # Skip the placeholder item
                        selected_prompt = history[
                            active - 1
                        ]  # -1 because of placeholder
                        text_buffer.set_text(selected_prompt)
                        text_view.grab_focus()
                        text_buffer.select_range(
                            text_buffer.get_start_iter(), text_buffer.get_end_iter()
                        )

                history_combo.connect("changed", on_history_changed)

            # Add progress widget
            progress_frame, progress_label = self._create_progress_widget()
            content_area.pack_start(progress_frame, False, False, 0)

            # Show all widgets
            content_area.show_all()

            # Focus the text view and select all text for easy editing
            text_view.grab_focus()
            text_buffer.select_range(
                text_buffer.get_start_iter(), text_buffer.get_end_iter()
            )

            # Run dialog in loop to handle Settings button
            print("DEBUG: About to call dialog.run()...")
            while True:
                response = dialog.run()
                print(f"DEBUG: Dialog response: {response}")

                if response == Gtk.ResponseType.OK:
                    # Validate the prompt
                    start_iter = text_buffer.get_start_iter()
                    end_iter = text_buffer.get_end_iter()
                    prompt = text_buffer.get_text(start_iter, end_iter, False).strip()

                    # Check if user entered actual content (not just placeholder)
                    placeholder_texts = [
                        "Describe what you want to generate...",
                        "Describe what to fill the selection with (e.g. 'remove object', 'a wooden fence')",
                    ]

                    is_placeholder = prompt in placeholder_texts or not prompt.strip()

                    if is_placeholder:
                        # Show error message and keep dialog open
                        error_dialog = Gtk.MessageDialog(
                            parent=dialog,
                            flags=Gtk.DialogFlags.MODAL,
                            message_type=Gtk.MessageType.WARNING,
                            buttons=Gtk.ButtonsType.OK,
                            text="Please enter a prompt description",
                        )
                        error_dialog.format_secondary_text(
                            "You need to describe what you want to generate or change before proceeding."
                        )
                        error_dialog.run()
                        error_dialog.destroy()
                        continue  # Keep the main dialog open

                    # Get selected mode
                    selected_mode = "contextual"  # default
                    if show_mode_selection and full_radio and full_radio.get_active():
                        selected_mode = "full_image"
                    elif (
                        show_mode_selection
                        and focused_radio
                        and focused_radio.get_active()
                    ):
                        selected_mode = "contextual"
                    # If no mode selection UI, use default "contextual" (for image generator)

                    print(
                        f"DEBUG: Got prompt text: '{prompt}', mode: '{selected_mode}', disabling OK button..."
                    )
                    # Disable OK button to prevent multiple clicks
                    ok_button.set_sensitive(False)
                    ok_button.set_label("Processing...")

                    # Update progress
                    self._update_progress(progress_label, "Preparing request...")

                    if prompt:
                        self._add_to_prompt_history(prompt)
                        # Save the selected mode to config
                        self.config["last_mode"] = selected_mode
                        self._save_config()

                    # Reset cancel flag for new operation
                    self._cancel_requested = False

                    # Add cancel handler to keep dialog responsive during processing
                    def on_dialog_response(dialog, response_id):
                        if response_id == Gtk.ResponseType.CANCEL:
                            print("DEBUG: Cancel button clicked during processing")
                            self._cancel_requested = True
                            return True  # Keep dialog open
                        return False

                    dialog.connect("response", on_dialog_response)

                    # Return dialog, progress_label, and prompt data for processing
                    return (
                        (dialog, progress_label, prompt, selected_mode)
                        if prompt
                        else None
                    )
                elif response == Gtk.ResponseType.HELP:  # Settings button
                    print("DEBUG: Settings button clicked")
                    self._show_settings_dialog(dialog)
                    # Continue loop to keep main dialog open
                else:
                    print("DEBUG: Dialog cancelled, destroying...")
                    dialog.destroy()
                    return None

        except Exception as e:
            print(f"DEBUG: Dialog error: {e}")
            # Fallback to default prompt if dialog fails
            return default_text if default_text else "fill this area naturally"

    def _show_settings_dialog(self, parent_dialog):
        """Show settings dialog (local model, ComfyUI address, history, debug)"""
        try:
            dialog = Gtk.Dialog(
                title="AI Plugin Settings",
                parent=parent_dialog,
                flags=Gtk.DialogFlags.MODAL,
            )

            # Set up dialog properties
            dialog.set_default_size(500, 400)
            dialog.set_resizable(True)

            # Add buttons
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            save_button = dialog.add_button("Save", Gtk.ResponseType.OK)
            save_button.set_can_default(True)
            save_button.grab_default()

            # Add content
            content_area = dialog.get_content_area()
            content_area.set_spacing(15)
            content_area.set_margin_start(20)
            content_area.set_margin_end(20)
            content_area.set_margin_top(20)
            content_area.set_margin_bottom(20)

            # Local model section (gimp-setup patch)
            provider_frame = Gtk.Frame(label="AI Model")
            provider_box = Gtk.VBox(spacing=10)
            provider_box.set_margin_start(10)
            provider_box.set_margin_end(10)
            provider_box.set_margin_top(10)
            provider_box.set_margin_bottom(10)

            provider_label = Gtk.Label(
                label="Local ComfyUI model used by Generative Fill\n"
                      "and Image Generator:"
            )
            provider_label.set_halign(Gtk.Align.START)
            provider_box.pack_start(provider_label, False, False, 0)

            provider_combo = Gtk.ComboBoxText()
            for provider_id, provider_name in ai_providers.PROVIDERS.items():
                provider_combo.append(provider_id, provider_name)
            provider_combo.set_active_id(self._get_provider())
            provider_box.pack_start(provider_combo, False, False, 0)

            comfyui_label = Gtk.Label(
                label="ComfyUI URL (local, must be running):"
            )
            comfyui_label.set_halign(Gtk.Align.START)
            provider_box.pack_start(comfyui_label, False, False, 0)

            comfyui_entry = Gtk.Entry()
            comfyui_entry.set_text(ai_providers.get_comfyui_url(self.config))
            provider_box.pack_start(comfyui_entry, False, False, 0)

            provider_frame.add(provider_box)
            content_area.pack_start(provider_frame, False, False, 0)

            # Prompt History section
            history_frame = Gtk.Frame(label="Prompt History")
            history_box = Gtk.VBox(spacing=10)
            history_box.set_margin_start(10)
            history_box.set_margin_end(10)
            history_box.set_margin_top(10)
            history_box.set_margin_bottom(10)

            # History count
            history_count = len(self._get_prompt_history())
            count_label = Gtk.Label(label=f"Stored prompts: {history_count}")
            count_label.set_halign(Gtk.Align.START)
            history_box.pack_start(count_label, False, False, 0)

            # Clear history button
            clear_button = Gtk.Button(label="Clear Prompt History")
            clear_button.connect("clicked", self._on_clear_history_clicked)
            history_box.pack_start(clear_button, False, False, 0)

            history_frame.add(history_box)
            content_area.pack_start(history_frame, False, False, 0)

            # Debug Settings section
            debug_frame = Gtk.Frame(label="Debug Settings")
            debug_box = Gtk.VBox(spacing=10)
            debug_box.set_margin_start(10)
            debug_box.set_margin_end(10)
            debug_box.set_margin_top(10)
            debug_box.set_margin_bottom(10)

            # Debug mode checkbox
            debug_checkbox = Gtk.CheckButton()
            debug_dir = tempfile.gettempdir()
            debug_checkbox.set_label(f"Save debug images to {debug_dir}")
            debug_checkbox.set_active(self.config.get("debug_mode", False))
            debug_box.pack_start(debug_checkbox, False, False, 0)

            # Debug explanation
            debug_info = Gtk.Label()
            debug_info.set_text(
                "Saves intermediate AI processing images for troubleshooting"
            )
            debug_info.set_halign(Gtk.Align.START)
            debug_info.get_style_context().add_class("dim-label")
            debug_box.pack_start(debug_info, False, False, 0)

            debug_frame.add(debug_box)
            content_area.pack_start(debug_frame, False, False, 0)

            # Show all widgets
            content_area.show_all()

            # Run dialog
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                # Save model settings (gimp-setup patch)
                active_provider = provider_combo.get_active_id()
                if active_provider:
                    self.config["provider"] = active_provider
                    print(f"DEBUG: AI model set to {active_provider}")
                # Only an address typed here is stored, so the shared
                # comfyui-url file keeps working until it is overridden.
                new_comfyui_url = comfyui_entry.get_text().strip().rstrip("/")
                if new_comfyui_url and new_comfyui_url != ai_providers.get_comfyui_url(self.config):
                    self.config.setdefault("comfyui", {})["url"] = new_comfyui_url

                # Save debug mode setting
                debug_mode = debug_checkbox.get_active()
                self.config["debug_mode"] = debug_mode
                self._save_config()
                print(f"DEBUG: Debug mode set to {debug_mode}")

            dialog.destroy()

        except Exception as e:
            print(f"DEBUG: Settings dialog error: {e}")

    def _on_clear_history_clicked(self, button):
        """Handle clear history button click"""
        self.config["prompt_history"] = []
        self._save_config()
        print("DEBUG: Prompt history cleared")

    def _extract_context_region(self, image, context_info):
        """Extract context region and scale to the optimal shape"""
        try:
            print("DEBUG: Extracting context region for AI with optimal shape")

            # Get parameters for the extract region
            ctx_x1, ctx_y1, ctx_width, ctx_height = context_info["extract_region"]
            target_shape = context_info["target_shape"]
            target_width, target_height = target_shape
            orig_width = image.get_width()
            orig_height = image.get_height()

            print(
                f"DEBUG: Extract region: ({ctx_x1},{ctx_y1}) to ({ctx_x1+ctx_width},{ctx_y1+ctx_height}) size={ctx_width}x{ctx_height}"
            )
            print(f"DEBUG: Original image: {orig_width}x{orig_height}")
            print(f"DEBUG: Target shape: {target_width}x{target_height}")

            # Create a new canvas with the extract region size
            extract_image = Gimp.Image.new(ctx_width, ctx_height, image.get_base_type())
            if not extract_image:
                return False, "Failed to create extract canvas", None

            # Calculate what part of the original image intersects with our extract region
            intersect_x1 = max(0, ctx_x1)
            intersect_y1 = max(0, ctx_y1)
            intersect_x2 = min(orig_width, ctx_x1 + ctx_width)
            intersect_y2 = min(orig_height, ctx_y1 + ctx_height)

            intersect_width = intersect_x2 - intersect_x1
            intersect_height = intersect_y2 - intersect_y1

            print(
                f"DEBUG: Image intersection: ({intersect_x1},{intersect_y1}) to ({intersect_x2},{intersect_y2})"
            )
            print(f"DEBUG: Intersection size: {intersect_width}x{intersect_height}")

            if intersect_width > 0 and intersect_height > 0:
                # Create a temporary image with just the intersecting region
                temp_image = image.duplicate()
                temp_image.crop(
                    intersect_width, intersect_height, intersect_x1, intersect_y1
                )

                # Create a layer from this region
                merged_layer = temp_image.merge_visible_layers(
                    Gimp.MergeType.CLIP_TO_IMAGE
                )
                if not merged_layer:
                    temp_image.delete()
                    extract_image.delete()
                    return False, "Failed to merge layers", None

                # Copy this layer to our extract canvas at the correct position
                layer_copy = Gimp.Layer.new_from_drawable(merged_layer, extract_image)
                extract_image.insert_layer(layer_copy, None, 0)

                # Position the layer correctly within the extract region
                # The layer should be at the same relative position as in the extract region
                paste_x = intersect_x1 - ctx_x1  # Offset within the extract region
                paste_y = intersect_y1 - ctx_y1  # Offset within the extract region
                layer_copy.set_offsets(paste_x, paste_y)

                print(
                    f"DEBUG: Placed image content at offset ({paste_x},{paste_y}) within extract region"
                )

                # Clean up temp image
                temp_image.delete()
            else:
                print(
                    "DEBUG: No intersection with original image - creating empty extract region"
                )

            # Scale and pad to the target shape (preserve aspect ratio)
            if ctx_width != target_width or ctx_height != target_height:
                # Get padding info to preserve aspect ratio
                if "padding_info" in context_info:
                    padding_info = context_info["padding_info"]
                    scale_factor = padding_info["scale_factor"]
                    scaled_w, scaled_h = padding_info["scaled_size"]
                    pad_left, pad_top, pad_right, pad_bottom = padding_info["padding"]

                    print(f"DEBUG: Using aspect-ratio preserving scaling:")
                    print(f"  Scale factor: {scale_factor}")
                    print(f"  Scaled size: {scaled_w}x{scaled_h}")
                    print(
                        f"  Padding: left={pad_left}, top={pad_top}, right={pad_right}, bottom={pad_bottom}"
                    )

                    # First scale preserving aspect ratio
                    if scale_factor != 1.0:
                        extract_image.scale(scaled_w, scaled_h)
                        print(
                            f"DEBUG: Scaled to {scaled_w}x{scaled_h} preserving aspect ratio"
                        )

                    # Then add padding to reach target dimensions
                    if pad_left > 0 or pad_top > 0 or pad_right > 0 or pad_bottom > 0:
                        # Resize canvas to add padding
                        extract_image.resize(
                            target_width, target_height, pad_left, pad_top
                        )
                        print(
                            f"DEBUG: Added padding to reach {target_width}x{target_height}"
                        )
                else:
                    # Fallback: calculate padding on the fly
                    padding_info = calculate_padding_for_shape(
                        ctx_width, ctx_height, target_width, target_height
                    )
                    scale_factor = padding_info["scale_factor"]
                    scaled_w, scaled_h = padding_info["scaled_size"]
                    pad_left, pad_top, pad_right, pad_bottom = padding_info["padding"]

                    print(f"DEBUG: Calculating padding on the fly:")
                    print(f"  Scale factor: {scale_factor}")
                    print(
                        f"  Padding: left={pad_left}, top={pad_top}, right={pad_right}, bottom={pad_bottom}"
                    )

                    # First scale preserving aspect ratio
                    extract_image.scale(scaled_w, scaled_h)

                    # Then add padding
                    extract_image.resize(target_width, target_height, pad_left, pad_top)

                print(
                    f"DEBUG: Final extract image size: {target_width}x{target_height} (aspect ratio preserved)"
                )

            # Export to PNG
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_filename = temp_file.name

            try:
                # Export using GIMP's PNG export
                file = Gio.File.new_for_path(temp_filename)

                pdb_proc = Gimp.get_pdb().lookup_procedure("file-png-export")
                pdb_config = pdb_proc.create_config()
                pdb_config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
                pdb_config.set_property("image", extract_image)
                pdb_config.set_property("file", file)
                pdb_config.set_property("options", None)

                result = pdb_proc.run(pdb_config)
                if result.index(0) != Gimp.PDBStatusType.SUCCESS:
                    print(f"DEBUG: PNG export failed: {result.index(0)}")
                    extract_image.delete()
                    return False, "PNG export failed", None

                # Read the exported file and encode to base64
                with open(temp_filename, "rb") as f:
                    png_data = f.read()

                base64_data = base64.b64encode(png_data).decode("utf-8")

                # Clean up
                os.unlink(temp_filename)
                extract_image.delete()

                info = f"Extracted context region: {len(png_data)} bytes as PNG, base64 length: {len(base64_data)}"
                print(f"DEBUG: {info}")
                return True, info, base64_data

            except Exception as e:
                print(f"DEBUG: Context extraction export failed: {e}")
                if os.path.exists(temp_filename):
                    os.unlink(temp_filename)
                extract_image.delete()
                return False, f"Export failed: {str(e)}", None

        except Exception as e:
            print(f"DEBUG: Context extraction failed: {e}")
            return False, f"Context extraction error: {str(e)}", None


    def _calculate_full_image_context_extraction(self, image):
        """Calculate context extraction for the full image"""
        try:
            print("DEBUG: Calculating full image context extraction")

            # Get full image dimensions
            orig_width = image.get_width()
            orig_height = image.get_height()
            print(f"DEBUG: Original full image size: {orig_width}x{orig_height}")

            # Use full image bounds as "selection"
            full_x1, full_y1 = 0, 0
            full_x2, full_y2 = orig_width, orig_height

            print(
                f"DEBUG: Full image bounds: ({full_x1},{full_y1}) to ({full_x2},{full_y2})"
            )

            # For full image mode, select the optimal shape
            target_shape = get_optimal_shape(orig_width, orig_height)
            target_width, target_height = target_shape
            target_size = max(target_width, target_height)  # For backward compatibility

            print(f"DEBUG: Target shape: {target_width}x{target_height}")

            # For full image, the context covers the entire original image
            ctx_x1 = 0
            ctx_y1 = 0

            print(
                f"DEBUG: Context region covers entire image: {orig_width}x{orig_height}"
            )

            # Check if there's actually a selection - if not, use full image for transformation
            selection_bounds = Gimp.Selection.bounds(image)
            has_real_selection = (
                selection_bounds[0] if len(selection_bounds) > 0 else False
            )

            if has_real_selection:
                # Use actual selection bounds
                sel_bounds = (
                    selection_bounds[2],
                    selection_bounds[3],
                    selection_bounds[4],
                    selection_bounds[5],
                )
            else:
                # No selection - transform entire image ("Image to Image" mode)
                sel_bounds = (full_x1, full_y1, full_x2, full_y2)

            return {
                "mode": "full",
                "selection_bounds": sel_bounds,
                "extract_region": (
                    0,
                    0,
                    orig_width,
                    orig_height,
                ),  # Extract entire image
                "target_shape": target_shape,
                "target_size": max(target_shape),  # For backward compatibility
                "needs_padding": True,
                "padding_info": calculate_padding_for_shape(
                    orig_width, orig_height, target_shape[0], target_shape[1]
                ),
                "has_selection": has_real_selection,
                "original_bounds": (full_x1, full_y1, full_x2, full_y2),
            }

        except Exception as e:
            print(f"DEBUG: Failed to calculate full image context extraction: {e}")
            return None

    def _calculate_context_extraction(self, image):
        """Calculate smart context extraction area around selection using optimal shapes"""
        try:
            print("DEBUG: Calculating smart context extraction with optimal shapes")

            # Get image dimensions
            img_width = image.get_width()
            img_height = image.get_height()
            print(f"DEBUG: Original image size: {img_width}x{img_height}")

            # Check for selection
            selection_bounds = Gimp.Selection.bounds(image)
            print(f"DEBUG: Selection bounds raw: {selection_bounds}")

            if len(selection_bounds) < 5 or not selection_bounds[0]:
                print("DEBUG: No selection found, using center area")
                # Use new shape-aware function with no selection
                return extract_context_with_selection(
                    img_width,
                    img_height,
                    0,
                    0,
                    0,
                    0,
                    mode="focused",
                    has_selection=False,
                )

            # Extract selection bounds
            sel_x1 = selection_bounds[2] if len(selection_bounds) > 2 else 0
            sel_y1 = selection_bounds[3] if len(selection_bounds) > 3 else 0
            sel_x2 = selection_bounds[4] if len(selection_bounds) > 4 else 0
            sel_y2 = selection_bounds[5] if len(selection_bounds) > 5 else 0

            sel_width = sel_x2 - sel_x1
            sel_height = sel_y2 - sel_y1
            print(
                f"DEBUG: Selection: ({sel_x1},{sel_y1}) to ({sel_x2},{sel_y2}), size: {sel_width}x{sel_height}"
            )

            # Use new shape-aware function for calculation
            context_info = extract_context_with_selection(
                img_width,
                img_height,
                sel_x1,
                sel_y1,
                sel_x2,
                sel_y2,
                mode="focused",
                has_selection=True,
            )

            # Log the optimal shape selected
            print(f"DEBUG: Optimal shape selected: {context_info['target_shape']}")

            # Extract dimensions for any code that still expects target_size
            target_w, target_h = context_info["target_shape"]
            context_info["target_size"] = max(target_w, target_h)

            # Validate still works but now with shape support
            is_valid, error_msg = validate_context_info(context_info)
            if not is_valid:
                print(f"DEBUG: Context validation failed: {error_msg}")
                # Fallback to center extraction
                return extract_context_with_selection(
                    img_width,
                    img_height,
                    0,
                    0,
                    0,
                    0,
                    mode="focused",
                    has_selection=False,
                )

            # Add debug output for the calculated values
            extract_x1, extract_y1, extract_width, extract_height = context_info[
                "extract_region"
            ]
            target_w, target_h = context_info["target_shape"]

            print(
                f"DEBUG: Extract region: ({extract_x1},{extract_y1}) to ({extract_x1+extract_width},{extract_y1+extract_height}), size: {extract_width}x{extract_height}"
            )
            print(f"DEBUG: Target shape: {target_w}x{target_h}")

            if "padding_info" in context_info:
                padding_info = context_info["padding_info"]
                print(f"DEBUG: Scale factor: {padding_info['scale_factor']}")
                print(f"DEBUG: Padding: {padding_info['padding']}")

            return context_info

        except Exception as e:
            print(f"DEBUG: Context calculation failed: {e}")
            # Fallback to simple center extraction
            return extract_context_with_selection(
                img_width, img_height, 0, 0, 0, 0, mode="focused", has_selection=False
            )

    def _prepare_full_image(self, image):
        """Prepare full image for processing with optimal shape"""
        try:
            print("DEBUG: Preparing full image for transformation with optimal shape")

            width = image.get_width()
            height = image.get_height()

            print(f"DEBUG: Original image size: {width}x{height}")

            # Get the optimal shape for this image
            target_shape = get_optimal_shape(width, height)
            target_width, target_height = target_shape

            print(
                f"DEBUG: Optimal shape selected: {target_width}x{target_height}"
            )

            # Calculate padding info for this shape
            padding_info = calculate_padding_for_shape(
                width, height, target_width, target_height
            )
            scale = padding_info["scale_factor"]
            scaled_width, scaled_height = padding_info["scaled_size"]

            print(f"DEBUG: Scale factor: {scale:.3f}")
            print(f"DEBUG: Scaled size: {scaled_width}x{scaled_height}")

            # Create context_info with both old and new format for compatibility
            context_info = {
                "mode": "full_image",
                "original_size": (width, height),
                "scaled_size": (scaled_width, scaled_height),
                "scale_factor": scale,
                "target_shape": target_shape,  # New: optimal shape tuple
                "target_size": (
                    target_width
                    if target_width == target_height
                    else max(target_width, target_height)
                ),  # Old format fallback
                "padding_info": padding_info,
                "has_selection": True,  # Always true for this mode
            }

            return context_info

        except Exception as e:
            print(f"DEBUG: Full image preparation failed: {e}")
            # Fallback to square
            return {
                "mode": "full_image",
                "original_size": (1024, 1024),
                "scaled_size": (1024, 1024),
                "scale_factor": 1.0,
                "target_shape": (1024, 1024),
                "target_size": 1024,
                "has_selection": True,
            }

    def _extract_full_image(self, image, context_info):
        """Extract and scale the full image"""
        try:
            target_width, target_height = context_info["scaled_size"]
            print(
                f"DEBUG: Extracting full image, scaling to {target_width}x{target_height}"
            )

            # Create a copy of the image
            original_width = image.get_width()
            original_height = image.get_height()

            # Create image copy for processing
            temp_image = image.duplicate()

            # Flatten the image to get composite result
            if len(temp_image.get_layers()) > 1:
                temp_image.flatten()

            # Get the flattened layer
            layer = temp_image.get_layers()[0]

            # Scale the layer to target size
            layer.scale(target_width, target_height, False)

            # Scale the image canvas to match
            temp_image.scale(target_width, target_height)

            # Export to PNG in memory
            print("DEBUG: Exporting full image as PNG...")
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_path = temp_file.name

            # Use GIMP's export function like the existing code
            file = Gio.File.new_for_path(temp_path)
            pdb_proc = Gimp.get_pdb().lookup_procedure("file-png-export")
            pdb_config = pdb_proc.create_config()
            pdb_config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
            pdb_config.set_property("image", temp_image)
            pdb_config.set_property("file", file)
            pdb_config.set_property("options", None)
            result = pdb_proc.run(pdb_config)

            if result.index(0) != Gimp.PDBStatusType.SUCCESS:
                temp_image.delete()
                raise Exception("Failed to export full image")

            # Read the exported PNG
            with open(temp_path, "rb") as f:
                image_bytes = f.read()

            # Clean up
            os.unlink(temp_path)
            temp_image.delete()

            # Convert to base64 for API
            import base64

            image_data = base64.b64encode(image_bytes).decode("utf-8")

            print(
                f"DEBUG: Full image extracted: {len(image_bytes)} bytes, base64 length: {len(image_data)}"
            )
            return (
                True,
                f"Extracted full image: {len(image_bytes)} bytes as PNG, base64 length: {len(image_data)}",
                image_data,
            )

        except Exception as e:
            print(f"DEBUG: Full image extraction failed: {e}")
            return False, f"Full image extraction failed: {str(e)}", None

    def _run_threaded_operation(self, operation_func, operation_name, progress_label=None, max_wait_time=300):
        """Generic threaded wrapper for any operation to keep UI responsive"""
        import threading
        import time

        print(f"DEBUG: Starting threaded {operation_name}...")

        # gimp-setup patch: local models need far longer than an API call.
        max_wait_time = ai_providers.max_wait_seconds(
            self._get_provider(), max_wait_time
        )

        # Shared storage for results
        result = {
            "success": False,
            "message": "",
            "data": None,  # Generic data field
            "completed": False,
        }

        def operation_thread():
            try:
                result.update(operation_func())
            except Exception as e:
                print(f"DEBUG: [THREAD] {operation_name} exception: {e}")
                result["success"] = False
                result["message"] = str(e)
                result["data"] = None
            finally:
                result["completed"] = True

        # Start thread
        thread = threading.Thread(target=operation_thread)
        thread.daemon = True
        thread.start()

        # Keep UI responsive while waiting
        start_time = time.time()
        last_update_time = start_time

        print(f"DEBUG: Starting wait loop for {operation_name}, progress_label={progress_label is not None}")
        while not result["completed"]:
            current_time = time.time()
            elapsed = current_time - start_time

            # Update progress every 5 seconds
            if progress_label and current_time - last_update_time > 5:
                print(f"DEBUG: About to call _update_progress at {elapsed:.1f}s")
                minutes = int(elapsed // 60)
                if minutes > 0:
                    self._update_progress(
                        progress_label, f"Still processing... ({minutes}m elapsed)"
                    )
                else:
                    self._update_progress(
                        progress_label, f"Processing... ({int(elapsed)}s elapsed)"
                    )
                last_update_time = current_time
                print(f"DEBUG: _update_progress call completed")

            # Check for cancellation
            if self._check_cancel_and_process_events():
                print(f"DEBUG: {operation_name} cancelled by user")
                if progress_label:
                    self._update_progress(progress_label, "❌ Operation cancelled")
                # gimp-setup patch: stop the job on a local server too.
                ai_providers.cancel(self._get_provider(), self.config)
                result["success"] = False
                result["message"] = "Operation cancelled by user"
                break

            # Check for timeout
            if elapsed > max_wait_time:
                print(f"DEBUG: {operation_name} timeout after {max_wait_time} seconds")
                if progress_label:
                    self._update_progress(progress_label, "❌ Request timed out")
                result["success"] = False
                result["message"] = "Request timed out - check that ComfyUI is running"
                break

            time.sleep(0.1)  # Small sleep to prevent busy waiting

        return result["success"], result["message"], result["data"]

    def _call_generation(self, prompt, size="auto", progress_label=None):
        """Generate an image with the selected local model, with progress updates"""
        # gimp-setup patch: runs on the selected ComfyUI model.
        provider = self._get_provider()
        if progress_label:
            self._update_progress(
                progress_label, "🚀 Sending request to %s..." % provider
            )
        return ai_providers.generate_image(provider, self.config, prompt, size)

    def _call_generation_threaded(self, prompt, size="auto", progress_label=None):
        """Threaded wrapper for image generation to keep UI responsive"""
        def operation():
            success, message, image_data = self._call_generation(
                prompt, size, progress_label
            )
            return {"success": success, "message": message, "data": image_data}

        return self._run_threaded_operation(
            operation, "image generation call", progress_label
        )

    def _create_full_size_mask_then_scale(self, image, selection_channel, context_info):
        """Create mask at full original size, then scale/pad using same operations as image"""
        try:
            target_shape = context_info["target_shape"]
            target_width, target_height = target_shape
            padding_info = context_info["padding_info"]
            scale_factor = padding_info["scale_factor"]
            scaled_w, scaled_h = padding_info["scaled_size"]
            pad_left, pad_top, pad_right, pad_bottom = padding_info["padding"]

            # Determine the correct base size for mask creation
            # gimp-setup patch: where the mask's origin sits in the image.
            mask_origin_x = mask_origin_y = 0
            if context_info.get("mode") == "full":
                # Full image mode: create mask at full image size
                mask_base_width = image.get_width()
                mask_base_height = image.get_height()
                print(
                    f"DEBUG: Creating mask at full image size {mask_base_width}x{mask_base_height}, then scaling like image"
                )
            else:
                # Focused/contextual mode: create mask at extract region size
                extract_region = context_info["extract_region"]
                mask_origin_x, mask_origin_y = extract_region[0], extract_region[1]
                mask_base_width = extract_region[2]
                mask_base_height = extract_region[3]
                print(
                    f"DEBUG: Creating mask at extract region size {mask_base_width}x{mask_base_height}, then scaling like image"
                )

            # gimp-setup patch: build the mask with plain GIMP calls on a
            # cropped duplicate of the image. Upstream composited the
            # selection channel into a new image with GEGL, untranslated:
            # the mask came out empty (nothing to edit) unless the extract
            # region started at the image's top-left corner. A loosely
            # repainting model hid it; a local inpainter given an empty
            # mask returns the input unchanged. A duplicate keeps the
            # selection, and cropping keeps it aligned.
            mask_image = image.duplicate()
            if context_info.get("mode") != "full":
                mask_image.crop(
                    mask_base_width, mask_base_height, mask_origin_x, mask_origin_y
                )
            if mask_image.get_base_type() != Gimp.ImageBaseType.RGB:
                mask_image.convert_rgb()
            if mask_image.get_precision() != Gimp.Precision.U8_NON_LINEAR:
                mask_image.convert_precision(Gimp.Precision.U8_NON_LINEAR)

            mask_layer = Gimp.Layer.new(
                mask_image,
                "selection_mask",
                mask_base_width,
                mask_base_height,
                Gimp.ImageType.RGBA_IMAGE,
                100.0,
                Gimp.LayerMode.NORMAL,
            )
            mask_image.insert_layer(mask_layer, None, 0)
            for other_layer in mask_image.get_layers():
                if other_layer.get_id() != mask_layer.get_id():
                    mask_image.remove_layer(other_layer)

            # Black = preserve; the selection is cleared to transparent =
            # edit (the mask convention ai_providers expects).
            from gi.repository import Gegl

            mask_selection = Gimp.Selection.save(mask_image)
            Gimp.context_push()
            try:
                Gimp.Selection.none(mask_image)
                Gimp.context_set_foreground(Gegl.Color.new("black"))
                mask_layer.edit_fill(Gimp.FillType.FOREGROUND)
                mask_image.select_item(Gimp.ChannelOps.REPLACE, mask_selection)
                mask_layer.edit_clear()
                Gimp.Selection.none(mask_image)
            finally:
                Gimp.context_pop()
            mask_image.remove_channel(mask_selection)

            print(
                f"DEBUG: Created mask at original size with transparent selection areas"
            )

            # NOW scale using SAME operations as image
            if scale_factor != 1.0:
                mask_image.scale(scaled_w, scaled_h)
                print(f"DEBUG: Scaled mask to {scaled_w}x{scaled_h}")

            if pad_left > 0 or pad_top > 0 or pad_right > 0 or pad_bottom > 0:
                mask_image.resize(target_width, target_height, pad_left, pad_top)
                print(
                    f"DEBUG: Added padding to mask to reach {target_width}x{target_height}"
                )

            # Export (same as working code)
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_filename = temp_file.name

            file = Gio.File.new_for_path(temp_filename)
            pdb_proc = Gimp.get_pdb().lookup_procedure("file-png-export")
            pdb_config = pdb_proc.create_config()
            pdb_config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
            pdb_config.set_property("image", mask_image)
            pdb_config.set_property("file", file)
            pdb_config.set_property("options", None)

            result = pdb_proc.run(pdb_config)

            if result.index(0) != Gimp.PDBStatusType.SUCCESS:
                mask_image.delete()
                image.remove_channel(selection_channel)
                os.unlink(temp_filename)
                raise Exception("PNG export failed")

            with open(temp_filename, "rb") as f:
                png_data = f.read()

            os.unlink(temp_filename)
            mask_image.delete()
            image.remove_channel(selection_channel)

            print(f"DEBUG: Created full-size-then-scaled mask: {len(png_data)} bytes")
            return png_data

        except Exception as e:
            print(f"DEBUG: Full size mask creation failed: {e}")
            if "mask_image" in locals():
                mask_image.delete()
            if "selection_channel" in locals():
                image.remove_channel(selection_channel)
            raise Exception(f"Full size mask creation failed: {e}")

    def _create_context_mask(self, image, context_info, target_size):
        """Create mask from actual selection shape using pixel-by-pixel copying"""
        try:
            target_shape = context_info.get("target_shape", (target_size, target_size))
            target_width, target_height = target_shape
            print(
                f"DEBUG: Creating pixel-perfect selection mask {target_width}x{target_height}"
            )

            if not context_info["has_selection"]:
                raise Exception(
                    "No selection available - selection-shaped mask requires an active selection"
                )

            # Get extract region info
            ctx_x1, ctx_y1, ctx_width, ctx_height = context_info["extract_region"]
            print(
                f"DEBUG: Extract region: ({ctx_x1},{ctx_y1}) size {ctx_width}x{ctx_height}"
            )

            # Step 1: Save original selection as channel to preserve its exact shape
            selection_channel = Gimp.Selection.save(image)
            if not selection_channel:
                raise Exception("Failed to save selection as channel")
            print("DEBUG: Saved selection as channel for pixel copying")

            # For any mode with padding, use simplified approach that mirrors image processing
            if "padding_info" in context_info:
                return self._create_full_size_mask_then_scale(
                    image, selection_channel, context_info
                )

            # Step 2: Create target-shaped mask image (RGBA for transparency)
            mask_image = Gimp.Image.new(
                target_width, target_height, Gimp.ImageBaseType.RGB
            )
            if not mask_image:
                image.remove_channel(selection_channel)
                raise Exception("Failed to create mask image")

            mask_layer = Gimp.Layer.new(
                mask_image,
                "selection_mask",
                target_width,
                target_height,
                Gimp.ImageType.RGBA_IMAGE,
                100.0,
                Gimp.LayerMode.NORMAL,
            )
            if not mask_layer:
                mask_image.delete()
                image.remove_channel(selection_channel)
                raise Exception("Failed to create mask layer")

            mask_image.insert_layer(mask_layer, None, 0)

            # Fill with black background (preserve all areas initially)
            from gi.repository import Gegl

            black_color = Gegl.Color.new("black")
            Gimp.context_set_foreground(black_color)
            mask_layer.edit_fill(Gimp.FillType.FOREGROUND)
            print("DEBUG: Created black background mask (preserve all areas)")

            # Force layer update to make sure black fill is committed
            mask_layer.update(0, 0, target_width, target_height)

            # Explicitly ensure extension areas stay black by filling the entire target area
            print(
                f"DEBUG: Ensuring all extension areas are black in {target_width}x{target_height} mask"
            )

            # Step 3: Copy only the original image area, leave extended context white

            # Calculate where original image appears in context square
            orig_width, orig_height = image.get_width(), image.get_height()
            img_offset_x = max(
                0, -ctx_x1
            )  # where original image starts in context square
            img_offset_y = max(
                0, -ctx_y1
            )  # where original image starts in context square
            # Calculate where the original image content appears in the final padded target shape
            # Account for both extract region and padding
            if "padding_info" in context_info:
                padding_info = context_info["padding_info"]
                scale_factor = padding_info["scale_factor"]
                pad_left, pad_top, pad_right, pad_bottom = padding_info["padding"]

                # Original content is scaled and then padded
                img_end_x = min(
                    target_width - pad_left - pad_right, int(orig_width * scale_factor)
                )
                img_end_y = min(
                    target_height - pad_top - pad_bottom,
                    int(orig_height * scale_factor),
                )

                print(
                    f"DEBUG: Accounting for padding in mask - scale={scale_factor}, padding=({pad_left},{pad_top},{pad_right},{pad_bottom})"
                )
            else:
                # Fallback to simple calculation
                img_end_x = min(
                    ctx_width, orig_width - ctx_x1 if ctx_x1 >= 0 else orig_width
                )
                img_end_y = min(
                    ctx_height, orig_height - ctx_y1 if ctx_y1 >= 0 else orig_height
                )

            print(
                f"DEBUG: Original image appears at ({img_offset_x},{img_offset_y}) to ({img_end_x},{img_end_y}) in context square"
            )

            # Only process if there's an intersection
            if img_end_x > img_offset_x and img_end_y > img_offset_y:
                # Get buffers for pixel-level operations
                selection_buffer = selection_channel.get_buffer()
                if not selection_buffer:
                    mask_image.delete()
                    image.remove_channel(selection_channel)
                    raise Exception("Failed to get selection channel buffer")

                mask_shadow_buffer = mask_layer.get_shadow_buffer()
                if not mask_shadow_buffer:
                    mask_image.delete()
                    image.remove_channel(selection_channel)
                    raise Exception("Failed to get mask shadow buffer")

                print("DEBUG: Starting Gegl pixel copying from selection channel")

                # Create Gegl processing graph for selection shape copying
                graph = Gegl.Node()

                # Source 1: Current mask buffer (black background)
                mask_source = graph.create_child("gegl:buffer-source")
                mask_source.set_property("buffer", mask_layer.get_buffer())

                # Source 2: Selection channel buffer (contains exact selection shape)
                selection_source = graph.create_child("gegl:buffer-source")
                selection_source.set_property("buffer", selection_buffer)

                # Scale selection if needed to match the final image scaling
                if "padding_info" in context_info:
                    padding_info = context_info["padding_info"]
                    scale_factor = padding_info["scale_factor"]

                    if abs(scale_factor - 1.0) > 0.001:  # Need scaling
                        print(
                            f"DEBUG: Scaling selection channel by factor {scale_factor}"
                        )
                        scale_op = graph.create_child("gegl:scale-ratio")
                        scale_op.set_property("x", float(scale_factor))
                        scale_op.set_property("y", float(scale_factor))
                        selection_source.link(scale_op)
                        selection_input = scale_op
                    else:
                        selection_input = selection_source
                else:
                    selection_input = selection_source

                # Translate selection to correct position in padded target shape
                # For full image with padding, the selection has been scaled and needs padding offset
                if "padding_info" in context_info:
                    padding_info = context_info["padding_info"]
                    pad_left, pad_top, pad_right, pad_bottom = padding_info["padding"]

                    # Selection has already been scaled, just add padding offset
                    translate_x = pad_left
                    translate_y = pad_top

                    print(
                        f"DEBUG: Mask translation for padded image: translate by ({translate_x},{translate_y})"
                    )
                else:
                    # Original logic for non-padded extracts
                    translate_x = -ctx_x1
                    translate_y = -ctx_y1

                translate = graph.create_child("gegl:translate")
                translate.set_property("x", float(translate_x))
                translate.set_property("y", float(translate_y))

                # Connect scaled selection through translate to composite
                selection_input.link(translate)

                # Composite the translated selection over the black background
                # This preserves the black background in extension areas
                composite = graph.create_child("gegl:over")

                # Write to mask shadow buffer
                output = graph.create_child("gegl:write-buffer")
                output.set_property("buffer", mask_shadow_buffer)

                # Link the processing chain:
                # mask_source (black bg) + translated_selection → composite → output
                selection_source.link(translate)
                mask_source.link(composite)
                translate.connect_to("output", composite, "aux")
                composite.link(output)

                print(
                    f"DEBUG: Compositing selection over black background: translate by ({translate_x},{translate_y})"
                )

                # Process the graph to composite selection shape over black background
                output.process()
                print(
                    "DEBUG: Successfully composited selection shape over black background preserving extension areas"
                )

                # Flush and merge shadow buffer to make changes visible
                mask_shadow_buffer.flush()
                mask_layer.merge_shadow(True)
                print("DEBUG: Merged shadow buffer with base layer")
            else:
                print("DEBUG: No intersection - mask remains fully white")

            # Force complete layer update
            mask_layer.update(0, 0, target_width, target_height)

            # Force flush all changes to ensure PNG export sees the correct data
            Gimp.displays_flush()

            print("DEBUG: Successfully copied exact selection shape to mask using Gegl")

            # Step 4: Mask is already at target shape, no scaling needed
            # (Previous version scaled square masks, but we now create masks at target shape)
            print(f"DEBUG: Mask created at target shape {target_width}x{target_height}")

            # Step 4.5: Make selection areas transparent (the one simple change requested)
            # Current state: black background, white selection copied from channel
            # Needed: black background (preserve), transparent selection (inpaint)
            print("DEBUG: Making selection areas transparent for inpainting")
            scaled_mask_layer = mask_image.get_layers()[0]

            # Create a simple color-to-alpha operation to make selection areas transparent
            from gi.repository import Gegl

            transparency_graph = Gegl.Node()

            # Get layer buffer
            layer_buffer = scaled_mask_layer.get_buffer()
            shadow_buffer = scaled_mask_layer.get_shadow_buffer()

            # Source buffer
            buffer_source = transparency_graph.create_child("gegl:buffer-source")
            buffer_source.set_property("buffer", layer_buffer)

            # Convert white (selection) to transparent, keep everything else as-is
            color_to_alpha = transparency_graph.create_child("gegl:color-to-alpha")
            white_color = Gegl.Color.new("white")
            color_to_alpha.set_property("color", white_color)

            # Output buffer
            buffer_write = transparency_graph.create_child("gegl:write-buffer")
            buffer_write.set_property("buffer", shadow_buffer)

            # Process: source → color-to-alpha → output
            buffer_source.link(color_to_alpha)
            color_to_alpha.link(buffer_write)
            buffer_write.process()

            # Merge changes
            shadow_buffer.flush()
            scaled_mask_layer.merge_shadow(True)
            scaled_mask_layer.update(0, 0, target_size, target_size)

            print(
                "DEBUG: Selection areas are now transparent (inpaint), context/extension areas are black (preserved)"
            )

            # Step 5: Export as PNG
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                temp_filename = temp_file.name

            try:
                file = Gio.File.new_for_path(temp_filename)

                pdb_proc = Gimp.get_pdb().lookup_procedure("file-png-export")
                pdb_config = pdb_proc.create_config()
                pdb_config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
                pdb_config.set_property("image", mask_image)
                pdb_config.set_property("file", file)
                pdb_config.set_property("options", None)

                result = pdb_proc.run(pdb_config)
                if result.index(0) != Gimp.PDBStatusType.SUCCESS:
                    mask_image.delete()
                    image.remove_channel(selection_channel)
                    raise Exception(f"PNG export failed with status: {result.index(0)}")

                # Read the exported mask PNG
                with open(temp_filename, "rb") as f:
                    png_data = f.read()

                if len(png_data) == 0:
                    raise Exception("Exported PNG file is empty")

                # Clean up
                os.unlink(temp_filename)
                mask_image.delete()
                image.remove_channel(selection_channel)

                print(
                    f"DEBUG: Created pixel-perfect selection mask PNG: {len(png_data)} bytes"
                )
                return png_data

            except Exception as e:
                print(f"DEBUG: Mask export failed: {e}")
                if os.path.exists(temp_filename):
                    os.unlink(temp_filename)
                mask_image.delete()
                image.remove_channel(selection_channel)
                raise Exception(f"Mask export failed: {str(e)}")

        except Exception as e:
            print(f"DEBUG: Context mask creation failed: {e}")
            raise Exception(f"Selection-shaped mask creation failed: {str(e)}")

    def _apply_smart_mask_feathering(self, mask, image):
        """Apply smart feathering to mask edges for better blending while preserving selection size"""
        try:
            print("DEBUG: Applying smart mask feathering for enhanced edge blending")

            from gi.repository import Gegl

            # Get mask dimensions and buffer
            mask_width = mask.get_width()
            mask_height = mask.get_height()
            mask_buffer = mask.get_buffer()
            shadow_buffer = mask.get_shadow_buffer()

            print(f"DEBUG: Processing mask {mask_width}x{mask_height}")

            # Simplified approach: Apply graduated gaussian blur
            # This softens edges without changing the overall selection area
            graph = Gegl.Node()

            # Source: Current mask buffer
            source = graph.create_child("gegl:buffer-source")
            source.set_property("buffer", mask_buffer)

            # Apply moderate gaussian blur to soften edges
            # Use smaller blur to maintain selection size while softening transitions
            blur = graph.create_child("gegl:gaussian-blur")
            blur.set_property("std-dev-x", 4.0)  # Moderate blur for edge softening
            blur.set_property("std-dev-y", 4.0)

            # Output to shadow buffer
            output = graph.create_child("gegl:write-buffer")
            output.set_property("buffer", shadow_buffer)

            # Link the chain: source -> blur -> output
            source.link(blur)
            blur.link(output)

            # Process the graph
            print("DEBUG: Processing edge feathering...")
            output.process()

            # Merge changes
            shadow_buffer.flush()
            mask.merge_shadow(True)
            mask.update(0, 0, mask_width, mask_height)

            print(
                "DEBUG: Smart edge feathering applied - edges softened while preserving selection area"
            )

        except Exception as e:
            print(f"DEBUG: Smart mask feathering failed (using simple feathering): {e}")
            # Fallback: apply light gaussian blur to entire mask
            try:
                from gi.repository import Gegl

                mask_buffer = mask.get_buffer()
                shadow_buffer = mask.get_shadow_buffer()

                # Simple fallback: light gaussian blur on entire mask
                graph = Gegl.Node()

                source = graph.create_child("gegl:buffer-source")
                source.set_property("buffer", mask_buffer)

                blur = graph.create_child("gegl:gaussian-blur")
                blur.set_property("std-dev-x", 2.0)
                blur.set_property("std-dev-y", 2.0)

                output = graph.create_child("gegl:write-buffer")
                output.set_property("buffer", shadow_buffer)

                source.link(blur)
                blur.link(output)
                output.process()

                shadow_buffer.flush()
                mask.merge_shadow(True)
                mask.update(0, 0, mask.get_width(), mask.get_height())

                print("DEBUG: Applied fallback simple feathering")

            except Exception as e2:
                print(
                    f"DEBUG: Both smart and simple feathering failed, using original mask: {e2}"
                )

    def _sample_boundary_colors(self, image, context_info):
        """Sample colors around selection boundary for color matching"""
        try:
            print("DEBUG: Sampling boundary colors for color matching")

            if not context_info.get("has_selection", False):
                return None

            # Get selection bounds
            sel_x1, sel_y1, sel_x2, sel_y2 = context_info["selection_bounds"]

            # Sample from a ring around the selection edge
            # Inner ring: just inside selection
            # Outer ring: just outside selection
            sample_width = min(10, (sel_x2 - sel_x1) // 10)  # Adaptive sample width

            # Get the flattened image for color sampling
            merged_layer = None
            try:
                # Create a temporary flattened copy for sampling
                temp_image = image.duplicate()
                merged_layer = temp_image.flatten()

                # Sample colors using GEGL buffer operations
                from gi.repository import Gegl

                layer_buffer = merged_layer.get_buffer()

                # Sample pixels around selection boundary
                inner_samples = []
                outer_samples = []

                # Sample points along the selection perimeter
                sample_points = 20  # Number of sample points

                for i in range(sample_points):
                    # Calculate position along selection perimeter
                    t = i / sample_points

                    # Sample along top and bottom edges
                    if i < sample_points // 2:
                        x = int(sel_x1 + t * 2 * (sel_x2 - sel_x1))
                        y_inner = sel_y1 + sample_width // 2
                        y_outer = sel_y1 - sample_width // 2
                    else:
                        x = int(sel_x2 - (t - 0.5) * 2 * (sel_x2 - sel_x1))
                        y_inner = sel_y2 - sample_width // 2
                        y_outer = sel_y2 + sample_width // 2

                    # Ensure coordinates are within image bounds
                    x = max(0, min(x, image.get_width() - 1))
                    y_inner = max(0, min(y_inner, image.get_height() - 1))
                    y_outer = max(0, min(y_outer, image.get_height() - 1))

                    try:
                        # Sample inner color (inside selection)
                        inner_rect = Gegl.Rectangle.new(x, y_inner, 1, 1)
                        inner_pixel = layer_buffer.get(
                            inner_rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.CLAMP
                        )
                        if len(inner_pixel) >= 3:
                            inner_samples.append(
                                (inner_pixel[0], inner_pixel[1], inner_pixel[2])
                            )

                        # Sample outer color (outside selection)
                        outer_rect = Gegl.Rectangle.new(x, y_outer, 1, 1)
                        outer_pixel = layer_buffer.get(
                            outer_rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.CLAMP
                        )
                        if len(outer_pixel) >= 3:
                            outer_samples.append(
                                (outer_pixel[0], outer_pixel[1], outer_pixel[2])
                            )

                    except Exception as sample_e:
                        print(f"DEBUG: Sample point {i} failed: {sample_e}")
                        continue

                # Calculate average colors
                if inner_samples and outer_samples:
                    # Calculate averages
                    inner_avg = tuple(
                        sum(channel) // len(inner_samples)
                        for channel in zip(*inner_samples)
                    )
                    outer_avg = tuple(
                        sum(channel) // len(outer_samples)
                        for channel in zip(*outer_samples)
                    )

                    # Calculate differences for color correction
                    hue_diff = 0  # Simplified - could calculate actual hue difference
                    brightness_diff = (sum(outer_avg) // 3) - (sum(inner_avg) // 3)

                    color_info = {
                        "inner_avg": inner_avg,
                        "outer_avg": outer_avg,
                        "brightness_diff": brightness_diff,
                        "hue_diff": hue_diff,
                    }

                    print(
                        f"DEBUG: Sampled colors - Inner: {inner_avg}, Outer: {outer_avg}"
                    )
                    print(f"DEBUG: Brightness difference: {brightness_diff}")

                    return color_info
                else:
                    print("DEBUG: No valid color samples collected")
                    return None

            finally:
                # Clean up temporary image
                if merged_layer and hasattr(merged_layer, "get_image"):
                    temp_image = merged_layer.get_image()
                    if temp_image:
                        temp_image.delete()

        except Exception as e:
            print(f"DEBUG: Color sampling failed: {e}")
            return None

    def _apply_color_matching(self, result_layer, color_info):
        """Apply color correction to match sampled boundary colors"""
        if not color_info:
            print("DEBUG: No color info available - skipping color matching")
            return

        try:
            print("DEBUG: Applying color matching based on boundary samples")

            from gi.repository import Gegl

            # Get layer buffer
            layer_buffer = result_layer.get_buffer()
            shadow_buffer = result_layer.get_shadow_buffer()

            # Create color correction graph
            graph = Gegl.Node()

            # Source buffer
            source = graph.create_child("gegl:buffer-source")
            source.set_property("buffer", layer_buffer)

            # Apply brightness/levels adjustment if significant difference
            brightness_diff = color_info.get("brightness_diff", 0)
            if abs(brightness_diff) > 10:  # Only apply if difference is noticeable
                levels = graph.create_child("gegl:levels")

                # Adjust gamma based on brightness difference
                gamma_adjust = 1.0 + (brightness_diff / 255.0)
                gamma_adjust = max(0.5, min(2.0, gamma_adjust))  # Clamp gamma

                levels.set_property("in-low", 0.0)
                levels.set_property("in-high", 1.0)
                levels.set_property("gamma", gamma_adjust)
                levels.set_property("out-low", 0.0)
                levels.set_property("out-high", 1.0)

                source.link(levels)
                current_node = levels

                print(f"DEBUG: Applied gamma correction: {gamma_adjust}")
            else:
                current_node = source
                print(
                    "DEBUG: No significant brightness difference - skipping levels adjustment"
                )

            # Output buffer
            output = graph.create_child("gegl:write-buffer")
            output.set_property("buffer", shadow_buffer)

            current_node.link(output)

            # Process color correction
            output.process()

            # Merge changes
            shadow_buffer.flush()
            result_layer.merge_shadow(True)
            result_layer.update(
                0, 0, result_layer.get_width(), result_layer.get_height()
            )

            print("DEBUG: Color matching applied successfully")

        except Exception as e:
            print(f"DEBUG: Color matching failed: {e}")

    def _call_edit(
        self,
        image_data,
        mask_data,
        prompt,
        progress_label=None,
    ):
        """Inpaint the base64 PNG image_data through the selected local model"""
        try:
            print(f"DEBUG: Calling AI edit with prompt: {prompt}")

            # Validate inputs
            if not prompt or not prompt.strip():
                return False, "Error: Empty prompt provided", None

            if not image_data:
                return False, "Error: No image data provided", None

            if not mask_data:
                return False, "Error: No mask data provided", None

            # gimp-setup patch: the edit runs on the selected ComfyUI model;
            # the response is shaped like {"data": [{"b64_json": ...}]} so
            # the compositing code is shared.
            provider = self._get_provider()
            if progress_label:
                self._update_progress(
                    progress_label, "🚀 Sending request to %s..." % provider
                )
            return ai_providers.edit_image(
                provider, self.config, image_data, mask_data, prompt
            )

        except Exception as e:
            print(f"DEBUG: AI edit call failed: {e}")
            return False, f"AI edit call failed: {str(e)}", None

    def _call_edit_threaded(
        self,
        image_data,
        mask_data,
        prompt,
        progress_label=None,
    ):
        """Threaded wrapper for the AI edit call to keep UI responsive"""
        def operation():
            success, message, response = self._call_edit(
                image_data, mask_data, prompt, progress_label
            )
            return {"success": success, "message": message, "data": response}

        return self._run_threaded_operation(
            operation, "AI edit call", progress_label
        )

    def _download_and_composite_result(
        self, image, api_response, context_info, mode, color_info=None
    ):
        """Decode the AI result and composite it back to original image with proper masking"""
        try:
            print("DEBUG: Decoding and compositing AI result")

            # Validate inputs
            if not image:
                return False, "Error: No GIMP image provided"
            if not api_response or "data" not in api_response:
                return False, "Invalid API response - no data"
            if not api_response["data"] or len(api_response["data"]) == 0:
                return False, "Invalid API response - empty data array"

            result_data = api_response["data"][0]

            # ai_providers returns the result as base64 PNG data
            if "b64_json" in result_data:
                print("DEBUG: Processing base64 image data from the AI result")

                # Update progress for processing phase
                Gimp.progress_set_text("Processing AI result...")
                Gimp.progress_update(0.8)  # 80% - Processing data
                Gimp.displays_flush()

                # Decode base64 data
                import base64

                image_data = base64.b64decode(result_data["b64_json"])

            else:
                return False, "Invalid API response - no base64 image data"

            print(f"DEBUG: Processed {len(image_data)} bytes")

            # Save to temporary file
            Gimp.progress_set_text("Processing AI result...")
            Gimp.progress_update(0.9)  # 90% - Processing
            Gimp.displays_flush()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False, mode='wb') as temp_file:
                temp_filename = temp_file.name
                temp_file.write(image_data)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            # Save debug copy
            if self._is_debug_mode():
                debug_dir = tempfile.gettempdir()
                debug_filename = os.path.join(debug_dir, f"ai_result_{len(image_data)}_bytes.png")
                try:
                    with open(debug_filename, "wb") as debug_file:
                        debug_file.write(image_data)
                    print(f"DEBUG: Saved AI result to {debug_filename} for inspection")
                except Exception as e:
                    print(f"DEBUG: Could not save debug file: {e}")

            try:
                # Load the AI result into a temporary image
                Gimp.progress_set_text("Loading AI result...")
                Gimp.progress_update(0.95)  # 95% - Loading
                Gimp.displays_flush()

                file = Gio.File.new_for_path(temp_filename)
                ai_result_img = Gimp.file_load(
                    run_mode=Gimp.RunMode.NONINTERACTIVE, file=file
                )

                if not ai_result_img:
                    return False, "Failed to load AI result image"

                ai_layers = ai_result_img.get_layers()
                if not ai_layers or len(ai_layers) == 0:
                    ai_result_img.delete()
                    return False, "No layers found in AI result"

                ai_layer = ai_layers[0]
                print(
                    f"DEBUG: AI result dimensions: {ai_layer.get_width()}x{ai_layer.get_height()}"
                )

                # Get original image dimensions
                orig_width = image.get_width()
                orig_height = image.get_height()

                # Get context info for compositing
                sel_x1, sel_y1, sel_x2, sel_y2 = context_info["selection_bounds"]
                ctx_x1, ctx_y1, ctx_width, ctx_height = context_info["extract_region"]
                target_shape = context_info["target_shape"]

                print(f"DEBUG: Original image: {orig_width}x{orig_height}")
                print(
                    f"DEBUG: Selection bounds: ({sel_x1},{sel_y1}) to ({sel_x2},{sel_y2})"
                )
                print(
                    f"DEBUG: Extract region: ({ctx_x1},{ctx_y1}), size {ctx_width}x{ctx_height}"
                )

                # Scale AI result back to extract region size if needed
                if (
                    ai_layer.get_width() != ctx_width
                    or ai_layer.get_height() != ctx_height
                ):
                    scaled_img = ai_result_img.duplicate()

                    # For any mode with padding, remove padding first, then scale
                    if "padding_info" in context_info:
                        padding_info = context_info["padding_info"]
                        pad_left, pad_top, pad_right, pad_bottom = padding_info[
                            "padding"
                        ]
                        scaled_w, scaled_h = padding_info["scaled_size"]

                        print(
                            f"DEBUG: Removing padding from AI result: crop to {scaled_w}x{scaled_h}"
                        )
                        print(
                            f"DEBUG: Padding to remove: left={pad_left}, top={pad_top}, right={pad_right}, bottom={pad_bottom}"
                        )

                        # Crop to remove padding (get the actual content without black bars)
                        scaled_img.crop(scaled_w, scaled_h, pad_left, pad_top)
                        print(
                            f"DEBUG: Cropped AI result to {scaled_w}x{scaled_h} (removed padding)"
                        )

                        # Now scale the unpadded result to original size
                        scaled_img.scale(ctx_width, ctx_height)
                        print(
                            f"DEBUG: Scaled unpadded result to original size: {ctx_width}x{ctx_height}"
                        )
                    else:
                        # Normal scaling for non-padded results
                        scaled_img.scale(ctx_width, ctx_height)
                        print(
                            f"DEBUG: Scaled AI result to extract region size: {ctx_width}x{ctx_height}"
                        )

                    scaled_layers = scaled_img.get_layers()
                    if scaled_layers:
                        ai_layer = scaled_layers[0]

                # USE PURE COORDINATE FUNCTION FOR PLACEMENT
                placement = calculate_placement_coordinates(context_info)
                paste_x = placement["paste_x"]
                paste_y = placement["paste_y"]
                result_width = placement["result_width"]
                result_height = placement["result_height"]

                # Create new layer in original image for the composited result
                result_layer = Gimp.Layer.new(
                    image,
                    "Generative Fill Result",
                    orig_width,
                    orig_height,
                    Gimp.ImageType.RGBA_IMAGE,
                    100.0,
                    Gimp.LayerMode.NORMAL,
                )

                # Insert layer at top
                image.insert_layer(result_layer, None, 0)

                print(f"DEBUG: USING PURE PLACEMENT FUNCTION:")
                print(f"DEBUG: AI result is {result_width}x{result_height} square")
                print(f"DEBUG: Placing at calculated position: ({paste_x},{paste_y})")
                print(f"DEBUG: GIMP will automatically clip to image bounds")

                # Copy the AI result content using simplified Gegl nodes
                from gi.repository import Gegl

                print(
                    f"DEBUG: Placing {ctx_width}x{ctx_height} AI result at ({paste_x},{paste_y})"
                )

                # Clear selection before Gegl processing to prevent clipping, then restore it
                print(
                    "DEBUG: Saving and clearing selection before Gegl processing to prevent clipping"
                )
                selection_channel = Gimp.Selection.save(image)
                Gimp.Selection.none(image)

                # Get buffers
                buffer = result_layer.get_buffer()
                shadow_buffer = result_layer.get_shadow_buffer()
                ai_buffer = ai_layer.get_buffer()

                # Create simplified Gegl processing graph
                graph = Gegl.Node()

                # Source: AI result square
                ai_input = graph.create_child("gegl:buffer-source")
                ai_input.set_property("buffer", ai_buffer)

                # Translate to context square position
                translate = graph.create_child("gegl:translate")
                translate.set_property("x", float(paste_x))
                translate.set_property("y", float(paste_y))

                # Write to shadow buffer without clipping
                output = graph.create_child("gegl:write-buffer")
                output.set_property("buffer", shadow_buffer)

                # Link simple chain: source -> translate -> output
                ai_input.link(translate)
                translate.link(output)

                # Process the graph
                try:
                    output.process()

                    # Flush and merge shadow buffer - update entire layer
                    shadow_buffer.flush()
                    result_layer.merge_shadow(True)

                    # Update the entire layer
                    result_layer.update(0, 0, orig_width, orig_height)

                    print(f"DEBUG: Updated entire layer: {orig_width}x{orig_height}")

                    print(
                        f"DEBUG: Successfully composited AI result using simplified Gegl graph"
                    )
                except Exception as e:
                    print(f"DEBUG: Gegl processing failed: {e}")
                    raise

                # Restore the original selection
                print("DEBUG: Restoring original selection after Gegl processing")
                try:
                    pdb = Gimp.get_pdb()
                    select_proc = pdb.lookup_procedure("gimp-image-select-item")
                    select_config = select_proc.create_config()
                    select_config.set_property("image", image)
                    select_config.set_property("operation", Gimp.ChannelOps.REPLACE)
                    select_config.set_property("item", selection_channel)
                    select_proc.run(select_config)
                    print("DEBUG: Selection successfully restored")
                except Exception as e:
                    print(f"DEBUG: Could not restore selection: {e}")
                # Clean up the temporary selection channel
                image.remove_channel(selection_channel)

                # Apply color matching for contextual mode (before masking)
                if mode == "contextual" and color_info:
                    print("DEBUG: Applying color matching to result layer...")
                    self._apply_color_matching(result_layer, color_info)

                # Create a layer mask for contextual mode only
                if mode == "contextual" and context_info["has_selection"]:
                    print(
                        "DEBUG: Creating selection-based mask for contextual mode while preserving full AI result in layer"
                    )

                    # Use GIMP's built-in selection mask type to automatically create properly shaped mask
                    # This preserves the full AI content in the layer but masks visibility to selection area
                    mask = result_layer.create_mask(Gimp.AddMaskType.SELECTION)
                    result_layer.add_mask(mask)

                    # Apply smart feathering to the mask for better blending
                    self._apply_smart_mask_feathering(mask, image)

                    print(
                        "DEBUG: Applied selection-based layer mask with smart feathering - enhanced blending at edges"
                    )
                    print(
                        "DEBUG: Core subject preserved at 100%, edges feathered for seamless integration"
                    )
                else:
                    print(
                        "DEBUG: No selection or full_image mode - layer shows full AI result without mask"
                    )

                # VALIDATION CHECKS
                print(f"DEBUG: === SIMPLIFIED ALIGNMENT VALIDATION ===")
                print(
                    f"DEBUG: Context square positioned at: ({paste_x},{paste_y}) with size {result_width}x{result_height}"
                )
                print(
                    f"DEBUG: Original selection was: ({sel_x1},{sel_y1}) to ({sel_x2},{sel_y2})"
                )
                print(
                    f"DEBUG: Since we work with true squares, alignment should be perfect"
                )
                print(
                    f"DEBUG: Selection coordinates within context square: ({sel_x1-paste_x},{sel_y1-paste_y}) to ({sel_x2-paste_x},{sel_y2-paste_y})"
                )

                # Clean up temporary image
                ai_result_img.delete()
                os.unlink(temp_filename)

                # Force display update
                Gimp.displays_flush()

                layer_count = len(image.get_layers())
                print(
                    f"DEBUG: Successfully composited AI result. Total layers: {layer_count}"
                )

                return (
                    True,
                    f"AI result composited as masked layer: '{result_layer.get_name()}' (total layers: {layer_count})",
                )

            except Exception as e:
                print(f"DEBUG: Compositing failed: {e}")
                if os.path.exists(temp_filename):
                    os.unlink(temp_filename)
                return False, f"Failed to composite result: {str(e)}"

        except Exception as e:
            print(f"DEBUG: Decode and composite failed: {e}")
            return False, f"Failed to process result: {str(e)}"

    def do_query_procedures(self):
        return [
            "gimp-ai-inpaint",
            "gimp-ai-layer-generator",
            "gimp-ai-settings",
        ]

    def do_create_procedure(self, name):
        if name == "gimp-ai-inpaint":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_inpaint, None
            )
            procedure.set_menu_label("Generative Fill...")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        elif name == "gimp-ai-layer-generator":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_layer_generator, None
            )
            procedure.set_menu_label("Image Generator")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        elif name == "gimp-ai-settings":
            procedure = Gimp.ImageProcedure.new(
                self, name, Gimp.PDBProcType.PLUGIN, self.run_settings, None
            )
            procedure.set_menu_label("Settings...")
            procedure.add_menu_path("<Image>/Filters/AI/")
            return procedure

        return None

    def run_inpaint(self, procedure, run_mode, image, drawables, config, run_data):
        print("DEBUG: AI Inpaint Selection called!")

        # Save the currently selected layers before any API calls that might clear them
        original_selected_layers = image.get_selected_layers()
        print(f"DEBUG: Saved {len(original_selected_layers)} originally selected layers")

        # Step 1: Check for active selection FIRST
        print("DEBUG: Checking for active selection...")
        selection_bounds = Gimp.Selection.bounds(image)
        has_selection = len(selection_bounds) >= 5 and selection_bounds[0]

        if not has_selection:
            print("DEBUG: No selection found - showing error message")
            Gimp.message(
                "❌ No Selection Found!\n\n"
                "Generative Fill requires an active selection to define the area to modify.\n\n"
                "Please:\n"
                "1. Use selection tools (Rectangle, Ellipse, Free Select, etc.)\n"
                "2. Select the area you want to fill\n"
                "3. Run Generative Fill again"
            )
            # Restore layer selection before returning
            if original_selected_layers:
                image.set_selected_layers(original_selected_layers)
                print("DEBUG: Restored layer selection after no canvas selection error")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        print("DEBUG: Selection found - proceeding with inpainting")

        # Step 2: Get user prompt
        print("DEBUG: About to show prompt dialog...")
        dialog_result = self._show_prompt_dialog(
            "Generative Fill",
            "",
            show_mode_selection=True,
            image=image,
        )
        print(f"DEBUG: Dialog returned: {repr(dialog_result)}")

        if not dialog_result:
            print("DEBUG: User cancelled prompt dialog")
            # Restore layer selection before returning
            if original_selected_layers:
                image.set_selected_layers(original_selected_layers)
                print("DEBUG: Restored layer selection after dialog cancel")
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        # Extract dialog, progress_label, prompt and mode from dialog result
        dialog, progress_label, prompt, selected_mode = dialog_result
        print(f"DEBUG: Extracted prompt: '{prompt}', mode: '{selected_mode}'")

        try:
            # Create progress callback for thread-to-UI communication
            progress_callback = self._create_progress_callback(progress_label)

            # Do GIMP operations on main thread, only thread the API call
            mode = self._get_processing_mode(selected_mode)
            print(f"DEBUG: Using processing mode: {mode}")

            self._update_progress(progress_label, "🔍 Processing image...")

            if mode == "full_image":
                print("DEBUG: Calculating full-image context extraction...")
                context_info = self._calculate_full_image_context_extraction(image)
            elif mode == "contextual":
                print("DEBUG: Calculating contextual selection-based extraction...")
                context_info = self._calculate_context_extraction(image)
            else:
                print("DEBUG: Unknown mode, defaulting to contextual extraction...")
                context_info = self._calculate_context_extraction(image)

            self._update_progress(progress_label, "🔍 Analyzing image context...")

            # Sample boundary colors for contextual mode (before inpainting)
            color_info = None
            if (
                mode == "contextual"
                and context_info
                and context_info.get("has_selection", False)
            ):
                print("DEBUG: Sampling boundary colors for color matching...")
                color_info = self._sample_boundary_colors(image, context_info)

            # Extract context region with padding (works for both modes)
            print("DEBUG: Extracting context region...")
            success, message, image_data = self._extract_context_region(
                image, context_info
            )
            if not success:
                self._update_progress(
                    progress_label, f"❌ Context extraction failed: {message}"
                )
                Gimp.message(f"❌ Context Extraction Failed: {message}")
                print(f"DEBUG: Context extraction failed: {message}")
                return procedure.new_return_values(
                    Gimp.PDBStatusType.CANCEL, GLib.Error()
                )
            print(f"DEBUG: Context extraction succeeded: {message}")

            self._update_progress(progress_label, "🎭 Creating selection mask...")

            # Create smart mask that respects selection within context
            print("DEBUG: Creating context-aware mask...")
            if not context_info:
                self._update_progress(progress_label, "❌ Context info not available")
                Gimp.message("❌ Context info not available")
                return procedure.new_return_values(
                    Gimp.PDBStatusType.CANCEL, GLib.Error()
                )

            mask_data = self._create_context_mask(
                image, context_info, context_info["target_size"]
            )

            self._update_progress(progress_label, "🚀 Starting AI processing...")

            api_success, api_message, api_response = self._call_edit_threaded(
                image_data,
                mask_data,
                prompt,
                progress_label=progress_label,
            )

            if api_success:
                print(f"DEBUG: AI API succeeded: {api_message}")
                self._update_progress(progress_label, "Processing AI response...")

                # Download and composite result with proper masking
                import_success, import_message = self._download_and_composite_result(
                    image, api_response, context_info, mode, color_info
                )

                if import_success:
                    self._update_progress(progress_label, "✅ Generative Fill Complete!")
                    print(f"DEBUG: AI Inpaint Complete - {import_message}")
                else:
                    self._update_progress(
                        progress_label, f"⚠️ Import Failed: {import_message}"
                    )
                    Gimp.message(
                        f"⚠️ AI Generated but Import Failed!\n\nPrompt: {prompt}\nAPI: {api_message}\nImport Error: {import_message}"
                    )
                    print(f"DEBUG: Import failed: {import_message}")
            else:
                # Check if this was a cancellation vs actual API failure
                if "cancelled" in api_message.lower():
                    self._update_progress(
                        progress_label, "❌ Operation cancelled by user"
                    )
                    Gimp.message("❌ Operation cancelled by user")
                else:
                    self._update_progress(
                        progress_label, f"❌ AI API Failed: {api_message}"
                    )
                    Gimp.message(f"❌ AI API Failed: {api_message}")
                print(f"DEBUG: AI API failed: {api_message}")

            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

        finally:
            # Always destroy the dialog
            if dialog:
                dialog.destroy()
            # Always restore original layer selection after any operation outcome
            if original_selected_layers:
                image.set_selected_layers(original_selected_layers)
                print("DEBUG: Restored layer selection after inpaint operation")

    def _add_layer_from_data(self, image, image_data):
        """Add image from raw data as a new layer"""
        try:
            import tempfile
            import os

            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png", mode='wb') as temp_file:
                temp_file.write(image_data)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_file_path = temp_file.name

            print(f"DEBUG: Saved image data to: {temp_file_path}")

            try:
                # Load the image as a new layer
                loaded_image = Gimp.file_load(
                    Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(temp_file_path)
                )
                source_layer = loaded_image.get_layers()[0]

                # Copy the layer to the current image
                new_layer = Gimp.Layer.new_from_drawable(source_layer, image)
                new_layer.set_name("AI Generated")

                # Add the layer to the image
                image.insert_layer(new_layer, None, 0)

                # Clean up
                loaded_image.delete()

                print("DEBUG: Successfully added generated layer")
                return True

            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass

        except Exception as e:
            print(f"ERROR: Failed to add layer from data: {str(e)}")
            return False

    def run_layer_generator(
        self, procedure, run_mode, image, drawables, config, run_data
    ):
        print("DEBUG: Image Generator called!")

        # Show prompt dialog (no mode selection for image generator)
        dialog_result = self._show_prompt_dialog(
            "Image Generator", "", show_mode_selection=False
        )
        if not dialog_result:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())

        # Extract dialog, progress_label, prompt and mode from dialog result
        dialog, progress_label, prompt, _ = (
            dialog_result  # Ignore mode for layer generator
        )

        try:
            # Update dialog immediately when processing starts
            self._update_progress(progress_label, "🎨 Generating image with AI...")

            # Use threaded generation to keep UI responsive like other functions
            self._update_progress(progress_label, "🚀 Starting image generation...")

            success, message, image_data = self._call_generation_threaded(
                prompt, size="auto", progress_label=progress_label
            )
            if success and image_data:
                # Create layer from the generated image data
                layer_success = self._add_layer_from_data(image, image_data)
                result = layer_success
            else:
                # Check if this was a cancellation vs actual failure
                if "cancelled" in message.lower():
                    self._update_progress(progress_label, "❌ Operation cancelled")
                    Gimp.message("❌ Operation cancelled by user")
                else:
                    self._update_progress(
                        progress_label, f"❌ Generation failed: {message}"
                    )
                    Gimp.message(f"❌ Generation failed: {message}")
                result = False
            if result:
                self._update_progress(
                    progress_label, "✅ Image layer generated successfully!"
                )
                Gimp.message("✅ Image layer generated successfully!")
                return procedure.new_return_values(
                    Gimp.PDBStatusType.SUCCESS, GLib.Error()
                )
            else:
                # Check if this was a cancellation vs actual failure
                if "cancelled" in message.lower():
                    # For cancellation, return SUCCESS status (user action, not an error)
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.SUCCESS, GLib.Error()
                    )
                else:
                    self._update_progress(
                        progress_label, "❌ Failed to generate image layer"
                    )
                    Gimp.message("❌ Failed to generate image layer")
                    return procedure.new_return_values(
                        Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error()
                    )
        except Exception as e:
            error_msg = f"Error generating image layer: {str(e)}"
            self._update_progress(progress_label, f"❌ Error: {str(e)}")
            print(f"ERROR: {error_msg}")
            Gimp.message(f"❌ {error_msg}")
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error()
            )
        finally:
            # Always destroy the dialog
            if dialog:
                dialog.destroy()

    def run_settings(self, procedure, run_mode, image, drawables, config, run_data):
        print("DEBUG: Settings called!")

        self._init_gimp_ui()
        self._show_settings_dialog(None)

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


# Entry point
if __name__ == "__main__":
    Gimp.main(GimpAIPlugin.__gtype__, sys.argv)

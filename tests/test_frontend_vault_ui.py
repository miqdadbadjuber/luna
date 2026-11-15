import unittest
from fastapi.testclient import TestClient
from luna.app import app
from tests import page_source


class TestFrontendVaultUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.response = cls.client.get("/")
        cls.source = page_source(cls.client)

    def test_index_renders_http_200(self):
        """GET / should render HTTP 200 with HTML content."""
        self.assertEqual(self.response.status_code, 200)
        self.assertIn("text/html", self.response.headers.get("content-type", ""))

    def test_provider_dropdown_markup_exists(self):
        """All three settings dropdowns are custom menus, not native selects."""
        html = self.source
        for element_id in (
            "llmProviderTrigger", "llmProviderMenu", "selectLlmProvider",
            "transcribeTrigger", "transcribeMenu", "selectTranscribeProvider",
            "openaiModelTrigger", "openaiModelMenu", "selectOpenaiModel", "openaiModelItems",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("function setLlmProvider", html)
        self.assertIn("function syncLlmProviderUI", html)
        self.assertIn("function selectTranscribe", html)
        self.assertIn("function selectOpenaiModel", html)
        self.assertIn("function toggleMenu", html)

    def test_ui_files_are_versioned_and_the_guide_has_one_source(self):
        self.assertNotIn("{{ASSET_VERSION}}", self.response.text)
        self.assertRegex(self.response.text, r'/assets/ui/app\.js\?v=\d+')
        res = self.client.get("/guide", follow_redirects=False)
        self.assertEqual((res.status_code, res.headers["location"]), (307, "/#guide"))

    def test_job_confirmation_states_rights_and_privacy(self):
        html = self.response.text
        self.assertIn('id="wsModalUsageNotice"', html)
        self.assertIn("rights to use", html)
        self.assertIn("providers chosen in Settings", html)

    def test_failed_job_can_be_dismissed(self):
        """A failed job must keep a working close control and a calm badge."""
        html = self.source
        self.assertIn("setCancelButtonVisible(true, 'Close')", html)
        self.assertNotIn('Failed <span class="animate-spin', html)
        self.assertIn("The download was interrupted", html)

    def test_ratio_labels_cover_every_supported_ratio(self):
        """3:4 and 1:1 must be labelled as themselves, not as 9:16 / 16:9."""
        for label in ("16:9 Landscape", "9:16 Portrait", "3:4 Portrait", "1:1 Square"):
            self.assertIn(label, self.source)
        self.assertIn("filterCountSquare", self.source)
        self.assertIn("ratioMetaFromSize", self.source)

    def test_navbar_tabs_exist(self):
        """Check for tabBtnStudio and tabBtnVault."""
        html = self.source
        self.assertIn('id="tabBtnStudio"', html)
        self.assertIn('id="tabBtnVault"', html)
        self.assertIn('id="mainTabsPill"', html)
        self.assertIn('class="t-tabs"', html)
        self.assertIn('class="t-tab', html)
        self.assertIn("Studio", html)
        self.assertIn("Media Vault", html)

    def test_main_content_sections_exist(self):
        """Check for section-studio and section-vault."""
        html = self.source
        self.assertIn('id="section-studio"', html)
        self.assertIn('id="section-vault"', html)
        # section-vault should initially have 'hidden' class
        self.assertIn('id="section-vault" class="hidden', html)

    def test_media_vault_gallery_elements_exist(self):
        """Check for vault gallery grid, storage header, filters, search, and empty state."""
        html = self.source
        self.assertIn('id="vaultGalleryGrid"', html)
        self.assertIn('id="vaultStoragePath"', html)
        self.assertIn('id="vaultTotalFiles"', html)
        self.assertIn('id="vaultTotalSize"', html)
        self.assertIn('id="vaultSearchInput"', html)
        self.assertIn('id="vaultEmptyState"', html)

        # Filter chips
        self.assertIn("All", html)
        self.assertIn("YouTube", html)
        self.assertIn("Instagram", html)
        self.assertIn("TikTok", html)
        self.assertIn("AI Clips", html)
        self.assertIn("Audio MP3", html)

    def test_delete_modal_exists(self):
        """Check for delete confirmation modal and its key elements."""
        html = self.source
        self.assertIn('id="deleteModal"', html)
        self.assertIn('id="deleteModalTitle"', html)
        self.assertIn('id="deleteModalPath"', html)
        self.assertIn('id="deleteModalConfirmBtn"', html)
        self.assertIn("Cancel", html)
        self.assertIn("Delete", html)

    def test_standard_workspace_detail_uses_unified_dropdown_and_icon_download(self):
        """Standard workspace header & cards use 3-dot dropdown + frameless download icon, without altering AI Clipper/Trimmer."""
        source = self.source
        css = self.client.get("/assets/ui/luna.css").text

        # Workspace header unified 3-dot button, old duplicate pencil/trash header controls removed
        self.assertIn('id="btnProjectDetailMenu"', source)
        self.assertNotIn('id="btnRenameInDetail"', source)
        self.assertNotIn('id="btnDeleteInDetail"', source)

        # AI Clipper & Trimmer remain untouched
        self.assertIn('id="btnClipperRename"', source)
        self.assertIn('id="btnClipperDelete"', source)
        self.assertIn("function renderClipperWorkflow", source)

        # Rename modal supports locked extension badge
        self.assertIn('id="renameWsExtBadge"', source)
        self.assertIn('id="renameWsTargetType"', source)

        # Dropdown labels & file card footer (no Open in Explorer, no white Download capsule button)
        self.assertIn('id="vaultCardMenuSelectLabel"', source)
        self.assertIn("Select Files", source)
        self.assertIn("toggleFileCardMenu", source)
        self.assertIn("luna-download-icon-link", source)
        self.assertIn("executeBulkDeleteVaultItems", source)
        render_files_block = source.split("function renderProjectFiles(proj)")[1].split("function toggleProjectDrawer")[0]
        self.assertNotIn("<span>Download</span>", render_files_block)
        self.assertIn("luna-download-icon-link", render_files_block)
        self.assertIn("toggleFileCardMenu", render_files_block)

        # Shared selection toolbar must not be blanket-hidden inside standard workspaces
        self.assertNotIn("body.in-workspace .vault-selection-bar", css)
        self.assertIn("#projectFilesGrid.is-selecting", css)
        self.assertIn(".luna-download-icon-link", css)

    def test_clipper_trimmer_card_actions_and_english_tooltips(self):
        """Verify AI Clipper / Trimmer cards match frameless icon actions, title-only rename, and English toolbar tooltips."""
        source = self.source
        css = self.client.get("/assets/ui/luna.css").text

        render_clipper_block = source.split("function renderClipperWorkflow(proj)")[1].split("(function initClipperCanvasControls()")[0]
        self.assertIn("vault-file-card", render_clipper_block)
        self.assertIn("vault-card-check", render_clipper_block)
        self.assertIn("toggleFileCardMenu", render_clipper_block)
        self.assertIn("luna-download-icon-link", render_clipper_block)
        self.assertNotIn("<span>Download</span>", render_clipper_block)
        self.assertNotIn("hover:border-white/[0.06]", render_clipper_block)
        self.assertNotIn("hover:bg-white/[0.04]", render_clipper_block)
        self.assertNotIn("hover:bg-white/[0.08]", render_clipper_block)
        self.assertIn(".caption-trigger-row:hover", css)
        self.assertIn("background: rgba(255, 255, 255, 0.06);", css)

        self.assertIn("targetType === 'clip-title'", source)
        self.assertIn("title_only: true", source)
        self.assertIn("#clipperBranchingClipsWrapper.is-selecting", css)

        toolbar_start = source.find('class="t-clipper-toolbar"')
        toolbar_snippet = source[toolbar_start:source.find("clipperZoomOut()", toolbar_start) + 200]
        self.assertNotIn("Reset Posisi Card", source)
        for tooltip in (
            "Reset Card Positions",
            "Rename Workspace",
            "Delete Workspace",
            "Zoom In",
            "Reset Zoom (100%)",
            "Zoom Out",
        ):
            self.assertIn(tooltip, toolbar_snippet)

    def test_required_js_functions_exist(self):
        """Verify presence of all required JS state and functions in index.html."""
        html = self.source
        required_functions = [
            "function switchMainTab",
            "function updateTabsPill",
            "function loadVaultItems",
            "function updateVaultBadge",
            "function updateVaultStatsUI",
            "function setVaultFilter",
            "function onVaultSearchInput",
            "function clearVaultSearch",
            "function renderVaultGallery",
            "function openVaultFolder",
            "function openVaultFile",
            "function confirmDeleteVaultItem",
            "function closeDeleteModal",
            "function executeDeleteVaultItem",
            "function triggerAction",
            "function openWorkspaceModal",
            "function fetchNextWorkspaceIndex",
            "function confirmAndStartProcess",
        ]
        for fn in required_functions:
            with self.subTest(fn=fn):
                self.assertIn(fn, html, f"Missing required JS function: {fn}")

    def test_api_calls_and_vault_urls_in_script(self):
        """Verify JS script calls appropriate vault endpoints and /media-vault/ URLs."""
        html = self.source
        self.assertIn("/api/vault", html)
        self.assertIn("/api/vault/open-file", html)
        self.assertIn("/api/vault/open-folder", html)
        self.assertIn("/media-vault/", html)

    def test_modal_styling_and_buttons(self):
        """Verify modals use neutral dark #171717 and use t-btn atoms instead of btn-luxe-cta."""
        html = self.source
        # No blueish #0c0e14 allowed
        self.assertNotIn("0c0e14", html)

        # Modals must use #171717
        self.assertIn('id="workspaceConfirmModal"', html)
        self.assertIn('id="renameWorkspaceModal"', html)
        self.assertIn('id="deleteModal"', html)

        # Verify buttons in modals do not use btn-luxe-cta
        rename_modal_snippet = html[html.find('id="renameWorkspaceModal"'):html.find('id="deleteModal"')]
        self.assertNotIn("btn-luxe-cta", rename_modal_snippet)
        self.assertIn("t-btn-primary", rename_modal_snippet)
        self.assertIn("t-btn-secondary", rename_modal_snippet)


if __name__ == "__main__":
    unittest.main()

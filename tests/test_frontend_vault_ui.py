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

    def test_failed_job_can_be_dismissed(self):
        """A failed job must keep a working close control and a calm badge."""
        html = self.source
        self.assertIn("setCancelButtonVisible(true, 'Close')", html)
        self.assertNotIn('Failed <span class="animate-spin', html)
        self.assertIn("The download was interrupted", html)

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

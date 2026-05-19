using System;
using System.Drawing;
using System.Windows.Forms;

namespace Axiom.RevitAddin.UI
{
    /// <summary>
    /// General-purpose Axiom text prompt dialog.
    /// Accepts free-form text that is routed through the prompt pipeline.
    /// Replaces the grid-specific GridPromptDialog for the Prompt button.
    /// </summary>
    public class AxiomPromptDialog : Form
    {
        private readonly TextBox _txtPrompt;
        private readonly TextBox _txtResult;
        private readonly Button _btnRun;
        private readonly Button _btnCancel;
        private readonly Label _lblPrompt;
        private readonly Label _lblResult;

        /// <summary>
        /// The prompt text entered by the user. Populated after Run is clicked.
        /// </summary>
        public string PromptText { get; private set; }

        public AxiomPromptDialog()
        {
            Text = "Axiom Prompt";
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.Sizable;
            MaximizeBox = true;
            MinimizeBox = false;
            ShowInTaskbar = false;
            Width = 560;
            Height = 420;
            MinimumSize = new Size(400, 320);

            _lblPrompt = new Label
            {
                Text = "Enter prompt:",
                Left = 16,
                Top = 12,
                Width = 200,
                AutoSize = true
            };

            _txtPrompt = new TextBox
            {
                Left = 16,
                Top = 32,
                Multiline = true,
                ScrollBars = ScrollBars.Vertical,
                AcceptsReturn = true,
                AcceptsTab = false,
                WordWrap = true,
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
                Width = 510,
                Height = 100
            };

            _btnRun = new Button
            {
                Text = "Run",
                Left = 16,
                Top = 140,
                Width = 80,
                Height = 28,
                Anchor = AnchorStyles.Top | AnchorStyles.Left
            };

            _btnCancel = new Button
            {
                Text = "Cancel",
                Left = 104,
                Top = 140,
                Width = 80,
                Height = 28,
                DialogResult = DialogResult.Cancel,
                Anchor = AnchorStyles.Top | AnchorStyles.Left
            };

            _lblResult = new Label
            {
                Text = "Result:",
                Left = 16,
                Top = 178,
                Width = 200,
                AutoSize = true
            };

            _txtResult = new TextBox
            {
                Left = 16,
                Top = 198,
                Multiline = true,
                ScrollBars = ScrollBars.Vertical,
                ReadOnly = true,
                BackColor = SystemColors.Window,
                WordWrap = true,
                Anchor = AnchorStyles.Top | AnchorStyles.Left
                       | AnchorStyles.Right | AnchorStyles.Bottom,
                Width = 510,
                Height = 160
            };

            CancelButton = _btnCancel;
            _btnRun.Click += OnRunClicked;

            Controls.Add(_lblPrompt);
            Controls.Add(_txtPrompt);
            Controls.Add(_btnRun);
            Controls.Add(_btnCancel);
            Controls.Add(_lblResult);
            Controls.Add(_txtResult);
        }

        private void OnRunClicked(object sender, EventArgs e)
        {
            string text = _txtPrompt.Text?.Trim();
            if (string.IsNullOrEmpty(text))
            {
                _txtResult.Text = "Please enter a prompt.";
                return;
            }

            PromptText = text;
            DialogResult = DialogResult.OK;
            Close();
        }

        /// <summary>
        /// Shows the dialog and returns the prompt text if Run was clicked.
        /// </summary>
        public static bool TryGetPrompt(IWin32Window owner, out string promptText)
        {
            using (var dlg = new AxiomPromptDialog())
            {
                var result = dlg.ShowDialog(owner);
                if (result == DialogResult.OK && !string.IsNullOrEmpty(dlg.PromptText))
                {
                    promptText = dlg.PromptText;
                    return true;
                }
            }

            promptText = null;
            return false;
        }
    }
}

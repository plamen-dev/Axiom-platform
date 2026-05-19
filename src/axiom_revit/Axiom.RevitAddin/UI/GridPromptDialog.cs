using System;
using System.Globalization;
using System.Windows.Forms;
using Axiom.Core.Models;

namespace Axiom.RevitAddin.UI
{
    public class GridPromptDialog : Form
    {
        private readonly NumericUpDown _numHorizontal;
        private readonly NumericUpDown _numVertical;
        private readonly NumericUpDown _numSpacing;
        private readonly Button _btnOk;
        private readonly Button _btnCancel;

        public GridParameters Parameters { get; private set; }

        public GridPromptDialog()
        {
            Text = "Axiom - Grid Prompt";
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            ShowInTaskbar = false;
            Width = 360;
            Height = 230;

            // Labels
            var lblHorizontal = new Label { Left = 16, Top = 20, Width = 140, Text = "Horizontal Count:" };
            var lblVertical = new Label { Left = 16, Top = 60, Width = 140, Text = "Vertical Count:" };
            var lblSpacing = new Label { Left = 16, Top = 100, Width = 140, Text = "Spacing (ft):" };

            // Inputs
            _numHorizontal = new NumericUpDown
            {
                Left = 170,
                Top = 18,
                Width = 150,
                Minimum = 1,
                Maximum = 200,
                Value = 5
            };

            _numVertical = new NumericUpDown
            {
                Left = 170,
                Top = 58,
                Width = 150,
                Minimum = 1,
                Maximum = 200,
                Value = 5
            };

            _numSpacing = new NumericUpDown
            {
                Left = 170,
                Top = 98,
                Width = 150,
                Minimum = 1,
                Maximum = 10000,
                DecimalPlaces = 2,
                Increment = 1,
                Value = 30
            };

            // Buttons
            _btnOk = new Button
            {
                Text = "OK",
                Left = 170,
                Top = 140,
                Width = 70,
                DialogResult = DialogResult.OK
            };

            _btnCancel = new Button
            {
                Text = "Cancel",
                Left = 250,
                Top = 140,
                Width = 70,
                DialogResult = DialogResult.Cancel
            };

            AcceptButton = _btnOk;
            CancelButton = _btnCancel;

            _btnOk.Click += OnOkClicked;

            Controls.Add(lblHorizontal);
            Controls.Add(lblVertical);
            Controls.Add(lblSpacing);
            Controls.Add(_numHorizontal);
            Controls.Add(_numVertical);
            Controls.Add(_numSpacing);
            Controls.Add(_btnOk);
            Controls.Add(_btnCancel);
        }

        private void OnOkClicked(object sender, EventArgs e)
        {
            Parameters = new GridParameters
            {
                HorizontalCount = (int)_numHorizontal.Value,
                VerticalCount = (int)_numVertical.Value,
                SpacingFeet = (double)_numSpacing.Value,
                Naming = "Default",
                Length = 0
            };

            DialogResult = DialogResult.OK;
            Close();
        }

        /// <summary>
        /// Shows the dialog and returns parameters if OK was pressed.
        /// </summary>
        public static bool TryGetParameters(IWin32Window owner, out GridParameters parameters)
        {
            using (var dlg = new GridPromptDialog())
            {
                var result = dlg.ShowDialog(owner);
                if (result == DialogResult.OK && dlg.Parameters != null)
                {
                    parameters = dlg.Parameters;
                    return true;
                }
            }

            parameters = null;
            return false;
        }
    }
}

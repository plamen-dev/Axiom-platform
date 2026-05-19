using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using System;
using Axiom.Core.Bridge;
using Axiom.RevitAddin.UI;

namespace Axiom.RevitAddin
{
    /// <summary>
    /// General-purpose prompt command for the Axiom ribbon button.
    /// Opens a free-text dialog and routes the prompt through the
    /// PromptDispatcher to registered capabilities.
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class PromptCommand : IExternalCommand
    {
        public Result Execute(
            ExternalCommandData commandData,
            ref string message,
            ElementSet elements)
        {
            UIDocument uiDoc = commandData.Application.ActiveUIDocument;
            if (uiDoc == null)
            {
                TaskDialog.Show(
                    "Axiom",
                    "No active Revit document.\n\n" +
                    "Open a Revit project and try again.");
                return Result.Failed;
            }

            Document doc = uiDoc.Document;
            View view = doc.ActiveView;

            if (!(view is ViewPlan) || view.IsTemplate)
            {
                TaskDialog.Show(
                    "Axiom",
                    "Prompt execution requires a plan view.\n\n" +
                    "Open a Floor Plan or Ceiling Plan and try again.");
                return Result.Failed;
            }

            // Show the general text prompt dialog
            string promptText;
            if (!AxiomPromptDialog.TryGetPrompt(null, out promptText))
            {
                return Result.Cancelled;
            }

            // Route through the prompt dispatcher
            var registry = App.GetRegistry();
            if (registry == null)
            {
                TaskDialog.Show(
                    "Axiom",
                    "Axiom capability registry is not initialized.\n\n" +
                    "This may indicate a startup error. Restart Revit.");
                return Result.Failed;
            }

            var dispatcher = new PromptDispatcher(registry);

            // Pre-dispatch check: resolve only (no execution) to detect clarification
            var preCheck = dispatcher.Resolve(promptText);
            if (preCheck.NeedsClarification)
            {
                TaskDialog.Show(
                    "Axiom - Clarification Needed",
                    $"Prompt: {promptText}\n\n{preCheck.Message}");
                return Result.Cancelled;
            }

            // Execute within a transaction (only for resolved prompts)
            using (Transaction tx = new Transaction(doc, "Axiom Prompt"))
            {
                try
                {
                    tx.Start();

                    var result = dispatcher.Dispatch(doc, promptText);

                    if (result.Success)
                    {
                        tx.Commit();

                        TaskDialog.Show(
                            "Axiom - Success",
                            $"Prompt: {promptText}\n\n{result.Message}");

                        return Result.Succeeded;
                    }
                    else
                    {
                        tx.RollBack();

                        TaskDialog.Show(
                            "Axiom - Failed",
                            $"Prompt: {promptText}\n\n{result.Message}");

                        return Result.Failed;
                    }
                }
                catch (Exception ex)
                {
                    if (tx.HasStarted())
                        tx.RollBack();

                    TaskDialog.Show(
                        "Axiom - Error",
                        $"Prompt: {promptText}\n\n" +
                        $"Unexpected error: {ex.Message}");

                    return Result.Failed;
                }
            }
        }
    }
}

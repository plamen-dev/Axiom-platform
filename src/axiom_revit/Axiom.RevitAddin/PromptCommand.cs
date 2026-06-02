using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Axiom.Core.Bridge;
using Axiom.Core.Compat;
using Axiom.RevitAddin.UI;
using Newtonsoft.Json;

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

            // Check if this is InventoryModel or SetParameterValue
            var preResolve = dispatcher.Resolve(promptText);
            bool isInventory = preResolve.Success &&
                               preResolve.CapabilityName == "InventoryModel";
            bool isSetParameterValue = preResolve.Success &&
                               preResolve.CapabilityName == "SetParameterValue";

            // Enforce plan view only for geometry-creating capabilities
            // InventoryModel and SetParameterValue can run from any view
            if (!isInventory && !isSetParameterValue)
            {
                View view = doc.ActiveView;
                if (!(view is ViewPlan) || view.IsTemplate)
                {
                    TaskDialog.Show(
                        "Axiom",
                        "This capability requires a plan view.\n\n" +
                        "Open a Floor Plan or Ceiling Plan and try again.\n" +
                        "(InventoryModel and SetParameterValue can run from any view.)");
                    return Result.Failed;
                }
            }

            // Pre-dispatch check: detect clarification needs
            if (preResolve.NeedsClarification)
            {
                TaskDialog.Show(
                    "Axiom - Clarification Needed",
                    $"Prompt: {promptText}\n\n{preResolve.Message}");
                return Result.Cancelled;
            }

            // InventoryModel: read-only, no transaction needed
            if (isInventory)
            {
                try
                {
                    var result = dispatcher.Dispatch(doc, promptText);

                    // Plan execution: category-by-category parameter schema
                    if (result.Success && result.CapabilityResult != null &&
                        result.CapabilityResult.Status == "PLAN_EXECUTION")
                    {
                        return ExecuteParameterSchemaPlan(
                            doc, dispatcher, promptText, result.CapabilityResult.OutputData);
                    }

                    if (result.Success && result.CapabilityResult != null)
                    {
                        var data = result.CapabilityResult.OutputData;

                        // Inject prompt traceability into output data
                        data["raw_prompt"] = promptText;
                        data["resolved_capability"] = result.CapabilityName ?? "InventoryModel";
                        data["result_class"] = result.CapabilityResult.Status == "SUCCESS" ? "success" : "failure";
                        data["source"] = "revit_prompt_dialog";
                        try { data["active_view"] = doc.ActiveView?.Name ?? ""; }
                        catch { data["active_view"] = ""; }

                        string scanMode = data.ContainsKey("scan_mode")
                            ? data["scan_mode"].ToString() : "summary";
                        int batchCount = data.ContainsKey("batch_count")
                            ? Convert.ToInt32(data["batch_count"]) : 0;

                        // Batched extraction: multiple JSON files written per batch
                        if (batchCount > 1 && data.ContainsKey("batch_manifest"))
                        {
                            var manifest = data["batch_manifest"] as Dictionary<string, object>;
                            string manifestPath = manifest != null && manifest.ContainsKey("manifest_path")
                                ? manifest["manifest_path"].ToString() : "";
                            int totalElements = data.ContainsKey("element_count")
                                ? Convert.ToInt32(data["element_count"]) : 0;
                            int errorCount = data.ContainsKey("error_count")
                                ? Convert.ToInt32(data["error_count"]) : 0;

                            string errorNote = errorCount > 0
                                ? $"\nSkipped elements (errors): {errorCount}\n"
                                : "";

                            TaskDialog.Show(
                                $"Axiom - InventoryModel (batched {scanMode})",
                                $"Status: SUCCESS\n" +
                                $"Scan mode: {scanMode} (batched)\n" +
                                $"Batches: {batchCount} completed\n" +
                                $"Total elements: {totalElements}\n" +
                                errorNote +
                                $"Duration: {result.CapabilityResult.DurationMs}ms\n" +
                                $"\nManifest: {manifestPath}\n" +
                                $"\nTo combine batches:\n" +
                                $"axiom inventory-combine --manifest \"{manifestPath}\"");

                            return Result.Succeeded;
                        }

                        // Single-pass extraction (no batching)
                        string jsonPath = PersistInventoryJson(
                            result.CapabilityResult, doc.Title);

                        int elemCount = data.ContainsKey("element_count")
                            ? Convert.ToInt32(data["element_count"]) : 0;
                        int instanceCount = data.ContainsKey("instance_count")
                            ? Convert.ToInt32(data["instance_count"]) : 0;
                        int typeCount = data.ContainsKey("type_count")
                            ? Convert.ToInt32(data["type_count"]) : 0;
                        int paramCount = data.ContainsKey("parameter_count")
                            ? Convert.ToInt32(data["parameter_count"]) : 0;
                        int paramDefCount = data.ContainsKey("parameter_definition_count")
                            ? Convert.ToInt32(data["parameter_definition_count"]) : 0;
                        int singleErrorCount = data.ContainsKey("error_count")
                            ? Convert.ToInt32(data["error_count"]) : 0;
                        string objectCategory = data.ContainsKey("object_category")
                            ? data["object_category"]?.ToString() ?? ""
                            : "";

                        string importHint = string.IsNullOrEmpty(jsonPath)
                            ? ""
                            : $"\nExported to:\n{jsonPath}\n\n" +
                              $"To import into artifact pipeline:\n" +
                              $"axiom inventory-import --file \"{jsonPath}\"";

                        string singleErrorNote = singleErrorCount > 0
                            ? $"\nSkipped elements (errors): {singleErrorCount}\n"
                            : "";

                        string nextSteps = scanMode == "summary"
                            ? "\n\nFor deeper scans:\n" +
                              "  - \"Run InventoryModel for Walls\" (category scan)\n" +
                              "  - \"Run InventoryModel for Walls batch 10000\" (batched)\n" +
                              "  - \"Run InventoryModel sample\" (first 100 elements)\n" +
                              "\nUse 'axiom inventory-plan' with summary JSON to plan safe extraction."
                            : "";

                        // Build dialog body
                        string dialogBody = $"Status: SUCCESS\nScan mode: {scanMode}\n";
                        if (!string.IsNullOrEmpty(objectCategory))
                            dialogBody += $"Object Category: {objectCategory}\n";
                        dialogBody += $"Instances scanned: {instanceCount}\n";
                        dialogBody += $"Types scanned: {typeCount}\n";
                        if (paramDefCount > 0)
                            dialogBody += $"Parameter definitions found: {paramDefCount}\n";
                        else if (paramCount > 0)
                            dialogBody += $"Parameters: {paramCount}\n";
                        dialogBody += singleErrorNote;
                        dialogBody += $"Duration: {result.CapabilityResult.DurationMs}ms";
                        dialogBody += importHint;
                        dialogBody += nextSteps;

                        TaskDialog.Show(
                            $"Axiom - InventoryModel ({scanMode})",
                            dialogBody);

                        return Result.Succeeded;
                    }
                    else
                    {
                        TaskDialog.Show(
                            "Axiom - Failed",
                            $"Prompt: {promptText}\n\n{result.Message}");
                        return Result.Failed;
                    }
                }
                catch (Exception ex)
                {
                    TaskDialog.Show(
                        "Axiom - Error",
                        $"Prompt: {promptText}\n\n" +
                        $"Unexpected error: {ex.Message}");
                    return Result.Failed;
                }
            }

            // SetParameterValue: preview (read-only) or apply (transactional)
            if (isSetParameterValue)
            {
                return ExecuteSetParameterValue(uiDoc, doc, dispatcher, promptText);
            }

            // Model-modifying capabilities: execute within a transaction
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

        /// <summary>
        /// Execute SetParameterValue capability.
        /// Preview mode: read-only, no transaction.
        /// Apply mode: transactional, modifies the model.
        /// Both modes produce evidence artifacts.
        /// </summary>
        private Result ExecuteSetParameterValue(
            UIDocument uiDoc,
            Document doc,
            PromptDispatcher dispatcher,
            string promptText)
        {
            string lower = promptText.ToLowerInvariant().Trim();
            bool isApply = lower.StartsWith("apply ");

            if (isApply)
            {
                // Apply mode: requires a transaction
                using (Transaction tx = new Transaction(doc, "Axiom SetParameterValue"))
                {
                    try
                    {
                        tx.Start();

                        var result = dispatcher.Dispatch(doc, promptText);

                        if (result.Success && result.CapabilityResult != null &&
                            result.CapabilityResult.Status == "SUCCESS")
                        {
                            tx.Commit();

                            // Add document metadata
                            result.CapabilityResult.OutputData["document_name"] = doc.Title ?? "";
                            try { result.CapabilityResult.OutputData["active_view"] = doc.ActiveView?.Name ?? ""; }
                            catch { result.CapabilityResult.OutputData["active_view"] = ""; }
                            result.CapabilityResult.OutputData["source"] = "revit_prompt_dialog";

                            // Persist evidence
                            string evidencePath = PersistSetParameterValueEvidence(
                                result.CapabilityResult, doc.Title, "apply");

                            var data = result.CapabilityResult.OutputData;
                            int successCount = data.ContainsKey("success_count")
                                ? Convert.ToInt32(data["success_count"]) : 0;
                            int failedCount = data.ContainsKey("failed_count")
                                ? Convert.ToInt32(data["failed_count"]) : 0;
                            string paramName = data.ContainsKey("parameter_name")
                                ? data["parameter_name"].ToString() : "";
                            string category = data.ContainsKey("category")
                                ? data["category"].ToString() : "";

                            string warningNote = result.CapabilityResult.Warnings.Count > 0
                                ? "\nWarnings:\n  " + string.Join("\n  ", result.CapabilityResult.Warnings)
                                : "";

                            string evidenceNote = string.IsNullOrEmpty(evidencePath)
                                ? "" : $"\n\nEvidence: {evidencePath}";

                            TaskDialog.Show(
                                "Axiom - SetParameterValue (apply)",
                                $"Status: SUCCESS\n" +
                                $"Mode: apply\n" +
                                $"Parameter: {paramName}\n" +
                                $"Category: {category}\n" +
                                $"Elements updated: {successCount}\n" +
                                $"Elements failed: {failedCount}\n" +
                                $"Duration: {result.CapabilityResult.DurationMs}ms" +
                                warningNote + evidenceNote);

                            return Result.Succeeded;
                        }
                        else
                        {
                            tx.RollBack();

                            TaskDialog.Show(
                                "Axiom - SetParameterValue Failed",
                                $"Prompt: {promptText}\n\n{result.Message}");
                            return Result.Failed;
                        }
                    }
                    catch (Exception ex)
                    {
                        if (tx.HasStarted())
                            tx.RollBack();

                        TaskDialog.Show(
                            "Axiom - SetParameterValue Error",
                            $"Prompt: {promptText}\n\n" +
                            $"Unexpected error: {ex.Message}");
                        return Result.Failed;
                    }
                }
            }
            else
            {
                // Preview mode: read-only, no transaction
                try
                {
                    var result = dispatcher.Dispatch(doc, promptText);

                    if (result.Success && result.CapabilityResult != null)
                    {
                        // Add document metadata
                        result.CapabilityResult.OutputData["document_name"] = doc.Title ?? "";
                        try { result.CapabilityResult.OutputData["active_view"] = doc.ActiveView?.Name ?? ""; }
                        catch { result.CapabilityResult.OutputData["active_view"] = ""; }
                        result.CapabilityResult.OutputData["source"] = "revit_prompt_dialog";

                        // Persist evidence
                        string evidencePath = PersistSetParameterValueEvidence(
                            result.CapabilityResult, doc.Title, "preview");

                        var data = result.CapabilityResult.OutputData;
                        int previewCount = data.ContainsKey("preview_count")
                            ? Convert.ToInt32(data["preview_count"]) : 0;
                        int skippedCount = data.ContainsKey("skipped_count")
                            ? Convert.ToInt32(data["skipped_count"]) : 0;
                        string paramName = data.ContainsKey("parameter_name")
                            ? data["parameter_name"].ToString() : "";
                        string category = data.ContainsKey("category")
                            ? data["category"].ToString() : "";
                        string value = data.ContainsKey("value")
                            ? data["value"].ToString() : "";

                        bool activeViewOnly = !data.ContainsKey("active_view_only")
                            || Convert.ToBoolean(data["active_view_only"]);

                        string skipNote = skippedCount > 0
                            ? $"\nSkipped (read-only/non-text): {skippedCount}" : "";

                        // Build element preview table and collect the IDs of the
                        // elements that are actually editable (status "preview").
                        // Apply will target exactly these IDs.
                        string elementPreview = "";
                        var previewableIds = new List<long>();
                        if (data.ContainsKey("elements"))
                        {
                            var elements = data["elements"] as List<Dictionary<string, object>>;
                            if (elements != null && elements.Count > 0)
                            {
                                elementPreview = "\n\nElement preview:";
                                foreach (var elem in elements)
                                {
                                    string elemId = elem.ContainsKey("element_id")
                                        ? elem["element_id"].ToString() : "?";
                                    string oldVal = elem.ContainsKey("old_value")
                                        ? elem["old_value"].ToString() : "";
                                    string status = elem.ContainsKey("status")
                                        ? elem["status"].ToString() : "";
                                    elementPreview += $"\n  [{elemId}] \"{oldVal}\" → \"{value}\" ({status})";

                                    if (status == "preview" && elem.ContainsKey("element_id"))
                                    {
                                        try { previewableIds.Add(Convert.ToInt64(elem["element_id"])); }
                                        catch { }
                                    }
                                }
                            }
                        }

                        string previewContent =
                            $"Status: SUCCESS — preview only, model NOT modified\n" +
                            $"Mode: preview\n" +
                            $"Parameter: {paramName}\n" +
                            $"Category: {category}\n" +
                            $"New value: \"{value}\"\n" +
                            $"Elements previewed: {previewCount}" +
                            skipNote +
                            $"\nDuration: {result.CapabilityResult.DurationMs}ms" +
                            elementPreview;

                        // Select/highlight the previewed elements in Revit so the
                        // user can confidently review what Apply will change. Best
                        // effort — never blocks preview.
                        bool selected = SelectAndShowElements(uiDoc, previewableIds);
                        if (selected)
                            previewContent +=
                                "\n\nPreviewed element(s) selected in Revit for review.";

                        // Interactive preview dialog: offer Apply / Open evidence
                        // folder / Close. Apply is only available here, after a
                        // successful preview, and reuses the previewed element IDs.
                        return ShowPreviewDialogAndMaybeApply(
                            doc, dispatcher, promptText, evidencePath, previewContent,
                            previewableIds, category, paramName, value, activeViewOnly);
                    }
                    else
                    {
                        TaskDialog.Show(
                            "Axiom - SetParameterValue Failed",
                            $"Prompt: {promptText}\n\n{result.Message}");
                        return Result.Failed;
                    }
                }
                catch (Exception ex)
                {
                    TaskDialog.Show(
                        "Axiom - SetParameterValue Error",
                        $"Prompt: {promptText}\n\n" +
                        $"Unexpected error: {ex.Message}");
                    return Result.Failed;
                }
            }
        }

        /// <summary>
        /// Show the interactive preview result dialog with Apply / Open
        /// evidence folder / Close. Apply is only reachable from here (after a
        /// successful preview) and edits exactly the previewed element IDs.
        /// Returns when the user closes/cancels or after Apply completes.
        /// </summary>
        private Result ShowPreviewDialogAndMaybeApply(
            Document doc,
            PromptDispatcher dispatcher,
            string promptText,
            string previewEvidencePath,
            string previewContent,
            List<long> previewableIds,
            string category,
            string parameterName,
            string value,
            bool activeViewOnly)
        {
            bool canApply = previewableIds.Count > 0;

            while (true)
            {
                var dlg = new TaskDialog("Axiom - SetParameterValue (preview)")
                {
                    MainInstruction = "Preview complete — model NOT modified",
                    MainContent = previewContent,
                    AllowCancellation = true,
                    CommonButtons = TaskDialogCommonButtons.Close,
                    DefaultButton = TaskDialogResult.Close
                };

                if (canApply)
                {
                    dlg.AddCommandLink(
                        TaskDialogCommandLinkId.CommandLink1,
                        $"Apply changes to {previewableIds.Count} element(s)",
                        $"Write \"{value}\" to {parameterName} on the previewed {category} " +
                        "in a single transaction.");
                }
                else
                {
                    dlg.FooterText =
                        "Apply unavailable: no editable previewed elements " +
                        "(all skipped as read-only/non-text).";
                }

                if (!string.IsNullOrEmpty(previewEvidencePath))
                {
                    dlg.AddCommandLink(
                        TaskDialogCommandLinkId.CommandLink2,
                        "Open evidence folder",
                        previewEvidencePath);
                }

                TaskDialogResult res = dlg.Show();

                if (res == TaskDialogResult.CommandLink1 && canApply)
                {
                    return ApplyFromPreview(
                        doc, dispatcher, promptText, previewEvidencePath,
                        previewableIds, category, parameterName, value, activeViewOnly);
                }

                if (res == TaskDialogResult.CommandLink2 ||
                    (res == TaskDialogResult.CommandLink1 && !canApply))
                {
                    OpenEvidenceFolder(previewEvidencePath);
                    // Re-show the dialog so the user can still apply or close.
                    continue;
                }

                // Close / Cancel — model not modified.
                return Result.Succeeded;
            }
        }

        /// <summary>
        /// Apply the previewed edit: re-execute SetParameterValue in apply mode
        /// against the exact previewed element IDs, inside a transaction. If any
        /// previewed element no longer resolves, the capability blocks the apply
        /// and this method surfaces the explanation. Evidence records that the
        /// apply was initiated from preview approval.
        /// </summary>
        private Result ApplyFromPreview(
            Document doc,
            PromptDispatcher dispatcher,
            string promptText,
            string previewEvidencePath,
            List<long> previewableIds,
            string category,
            string parameterName,
            string value,
            bool activeViewOnly)
        {
            var applyArgs = new Axiom.Core.Models.SetParameterValueParameters
            {
                Category = category,
                ParameterName = parameterName,
                Value = value,
                ElementCount = previewableIds.Count,
                Mode = "apply",
                ActiveViewOnly = activeViewOnly,
                RawPrompt = promptText,
                ElementIds = previewableIds
            };
            string argsJson = JsonConvert.SerializeObject(applyArgs);

            using (Transaction tx = new Transaction(doc, "Axiom SetParameterValue"))
            {
                try
                {
                    tx.Start();

                    var result = dispatcher.DispatchWithArgs(doc, "SetParameterValue", argsJson);

                    if (result.Success && result.CapabilityResult != null &&
                        result.CapabilityResult.Status == "SUCCESS")
                    {
                        tx.Commit();

                        var data = result.CapabilityResult.OutputData;
                        data["document_name"] = doc.Title ?? "";
                        try { data["active_view"] = doc.ActiveView?.Name ?? ""; }
                        catch { data["active_view"] = ""; }
                        data["source"] = "revit_prompt_dialog";
                        data["initiated_from"] = "preview_approval";
                        data["preview_evidence_path"] = previewEvidencePath ?? "";
                        data["element_ids_previewed"] = previewableIds;

                        string evidencePath = PersistSetParameterValueEvidence(
                            result.CapabilityResult, doc.Title, "apply");

                        int successCount = data.ContainsKey("success_count")
                            ? Convert.ToInt32(data["success_count"]) : 0;
                        int failedCount = data.ContainsKey("failed_count")
                            ? Convert.ToInt32(data["failed_count"]) : 0;

                        // Build old→new table from the apply results.
                        string changeDetail = "";
                        if (data.ContainsKey("elements"))
                        {
                            var elements = data["elements"] as List<Dictionary<string, object>>;
                            if (elements != null)
                            {
                                changeDetail = "\n\nChanges:";
                                foreach (var elem in elements)
                                {
                                    string elemId = elem.ContainsKey("element_id")
                                        ? elem["element_id"].ToString() : "?";
                                    string oldVal = elem.ContainsKey("old_value")
                                        ? elem["old_value"].ToString() : "";
                                    string newVal = elem.ContainsKey("new_value")
                                        ? elem["new_value"].ToString() : "";
                                    string status = elem.ContainsKey("status")
                                        ? elem["status"].ToString() : "";
                                    changeDetail += $"\n  [{elemId}] \"{oldVal}\" → \"{newVal}\" ({status})";
                                }
                            }
                        }

                        string warningNote = result.CapabilityResult.Warnings.Count > 0
                            ? "\nWarnings:\n  " + string.Join("\n  ", result.CapabilityResult.Warnings)
                            : "";
                        string evidenceNote = string.IsNullOrEmpty(evidencePath)
                            ? "" : $"\n\nEvidence: {evidencePath}";

                        TaskDialog.Show(
                            "Axiom - SetParameterValue (apply)",
                            $"Status: SUCCESS — applied from preview approval\n" +
                            $"Parameter: {parameterName}\n" +
                            $"Category: {category}\n" +
                            $"New value: \"{value}\"\n" +
                            $"Elements modified: {successCount}\n" +
                            $"Elements failed: {failedCount}\n" +
                            $"Duration: {result.CapabilityResult.DurationMs}ms" +
                            changeDetail + warningNote + evidenceNote);

                        return Result.Succeeded;
                    }
                    else
                    {
                        tx.RollBack();

                        string msg = result.CapabilityResult != null &&
                            result.CapabilityResult.Errors.Count > 0
                            ? string.Join("\n", result.CapabilityResult.Errors)
                            : result.Message;

                        TaskDialog.Show(
                            "Axiom - SetParameterValue Apply Blocked",
                            $"Apply did not modify the model.\n\n{msg}");
                        return Result.Failed;
                    }
                }
                catch (Exception ex)
                {
                    if (tx.HasStarted())
                        tx.RollBack();

                    TaskDialog.Show(
                        "Axiom - SetParameterValue Error",
                        $"Apply failed: {ex.Message}");
                    return Result.Failed;
                }
            }
        }

        /// <summary>
        /// Select and zoom/focus the previewed elements in Revit so the user
        /// can confidently review what Apply will change. Best-effort and
        /// read-only — selection/showing never modifies the model and never
        /// blocks the preview if it fails. Returns true if a selection was set.
        /// </summary>
        private static bool SelectAndShowElements(UIDocument uiDoc, List<long> elementIds)
        {
            if (uiDoc == null || elementIds == null || elementIds.Count == 0)
                return false;

            try
            {
                var ids = new List<ElementId>();
                foreach (long idValue in elementIds)
                    ids.Add(RevitElementIdCompat.FromLong(idValue));

                uiDoc.Selection.SetElementIds(ids);

                // Zoom/focus the selected elements so they are visible.
                try { uiDoc.ShowElements(ids); }
                catch (Exception ex) { Debug.WriteLine($"ShowElements failed: {ex.Message}"); }

                return true;
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"SelectAndShowElements failed: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Open the evidence folder in Windows Explorer. Best-effort.
        /// </summary>
        private static void OpenEvidenceFolder(string path)
        {
            if (string.IsNullOrEmpty(path) || !Directory.Exists(path))
                return;
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = path,
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"OpenEvidenceFolder failed: {ex.Message}");
            }
        }

        /// <summary>
        /// Persist SetParameterValue evidence artifacts to
        /// %LOCALAPPDATA%\Axiom\parameter_edit_runs\spv_YYYYMMDD_HHmmss\
        /// </summary>
        private static string PersistSetParameterValueEvidence(
            Axiom.Core.Capabilities.CapabilityResult capResult,
            string docTitle,
            string mode)
        {
            try
            {
                string localAppData = Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData);
                string baseDir = Path.Combine(localAppData, "Axiom", "parameter_edit_runs");

                string timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                string runDir = Path.Combine(baseDir, $"spv_{timestamp}");
                Directory.CreateDirectory(runDir);

                var data = capResult.OutputData;

                // request.json
                var request = new Dictionary<string, object>
                {
                    { "raw_prompt", data.ContainsKey("raw_prompt") ? data["raw_prompt"] : "" },
                    { "mode", mode },
                    { "category", data.ContainsKey("category") ? data["category"] : "" },
                    { "parameter_name", data.ContainsKey("parameter_name") ? data["parameter_name"] : "" },
                    { "value", data.ContainsKey("value") ? data["value"] : "" },
                    { "element_count", data.ContainsKey("requested_count") ? data["requested_count"] : 0 },
                    { "active_view_only", data.ContainsKey("active_view_only") ? data["active_view_only"] : true },
                    { "document_name", data.ContainsKey("document_name") ? data["document_name"] : docTitle ?? "" },
                    { "initiated_from", data.ContainsKey("initiated_from") ? data["initiated_from"] : (mode == "apply" ? "prompt" : "preview") },
                    { "targeted_by_ids", data.ContainsKey("targeted_by_ids") ? data["targeted_by_ids"] : false },
                    { "preview_evidence_path", data.ContainsKey("preview_evidence_path") ? data["preview_evidence_path"] : "" },
                    { "timestamp", DateTime.UtcNow.ToString("o") }
                };
                File.WriteAllText(
                    Path.Combine(runDir, "request.json"),
                    JsonConvert.SerializeObject(request, Formatting.Indented));

                // preview.json or changes.json
                string resultFile = mode == "apply" ? "changes.json" : "preview.json";
                File.WriteAllText(
                    Path.Combine(runDir, resultFile),
                    JsonConvert.SerializeObject(data, Formatting.Indented));

                // Linked preview snapshot (apply-from-preview only).
                string initiatedFrom = data.ContainsKey("initiated_from")
                    ? data["initiated_from"].ToString()
                    : (mode == "apply" ? "prompt" : "preview");
                bool isLinkedApply = mode == "apply" && initiatedFrom == "preview_approval";
                bool linkedPreviewCopied = false;
                bool linkedTargetIdsMatch = false;
                string linkedCopyStatus = "";
                if (isLinkedApply)
                {
                    linkedCopyStatus = WriteLinkedPreviewArtifacts(
                        runDir, data, out linkedTargetIdsMatch, out linkedPreviewCopied);
                    if (linkedCopyStatus == "missing_preview_json")
                    {
                        string pp = data.ContainsKey("preview_evidence_path")
                            ? data["preview_evidence_path"].ToString() : "";
                        capResult.Warnings.Add(
                            $"Linked preview snapshot missing: preview.json not found at \"{pp}\". " +
                            "Apply already succeeded; linked_preview_metadata.json records copy_status: missing_preview_json.");
                    }
                }

                // result_summary.md
                string paramName = data.ContainsKey("parameter_name")
                    ? data["parameter_name"].ToString() : "";
                string category = data.ContainsKey("category")
                    ? data["category"].ToString() : "";
                string value = data.ContainsKey("value")
                    ? data["value"].ToString() : "";
                bool modelModified = data.ContainsKey("model_modified")
                    && (bool)data["model_modified"];

                var md = new System.Text.StringBuilder();
                md.AppendLine("# SetParameterValue Result Summary");
                md.AppendLine();
                md.AppendLine($"- **Raw prompt:** {(data.ContainsKey("raw_prompt") ? data["raw_prompt"] : "")}");
                md.AppendLine($"- **Mode:** {mode}");
                md.AppendLine($"- **Initiated from:** {(data.ContainsKey("initiated_from") ? data["initiated_from"] : (mode == "apply" ? "prompt" : "preview"))}");
                md.AppendLine($"- **Targeted by element IDs:** {(data.ContainsKey("targeted_by_ids") ? data["targeted_by_ids"] : false)}");
                if (isLinkedApply)
                {
                    md.AppendLine($"- **Preview evidence path:** {(data.ContainsKey("preview_evidence_path") ? data["preview_evidence_path"] : "")}");
                    md.AppendLine($"- **Linked preview snapshot:** {(linkedPreviewCopied ? "linked_preview.json" : $"not copied ({linkedCopyStatus})")}");
                    md.AppendLine($"- **Target IDs match preview:** {linkedTargetIdsMatch.ToString().ToLowerInvariant()}");
                }
                md.AppendLine($"- **Category:** {category}");
                md.AppendLine($"- **Parameter:** {paramName}");
                md.AppendLine($"- **Value:** \"{value}\"");
                md.AppendLine($"- **Status:** {capResult.Status}");
                md.AppendLine($"- **Model modified:** {modelModified}");
                md.AppendLine($"- **Document:** {docTitle ?? ""}");
                md.AppendLine($"- **Active view:** {(data.ContainsKey("active_view") ? data["active_view"] : "")}");
                md.AppendLine($"- **Duration:** {capResult.DurationMs}ms");
                md.AppendLine($"- **Timestamp:** {DateTime.UtcNow:O}");
                md.AppendLine();

                // Element details
                if (data.ContainsKey("elements"))
                {
                    md.AppendLine("## Elements");
                    md.AppendLine();
                    md.AppendLine("| Element ID | Old Value | New Value | Status | Error |");
                    md.AppendLine("|-----------|-----------|-----------|--------|-------|");

                    var elements = data["elements"] as List<Dictionary<string, object>>;
                    if (elements != null)
                    {
                        foreach (var elem in elements)
                        {
                            string elemId = elem.ContainsKey("element_id")
                                ? elem["element_id"].ToString() : "";
                            string oldVal = elem.ContainsKey("old_value")
                                ? elem["old_value"].ToString() : "";
                            string newVal = elem.ContainsKey("new_value")
                                ? elem["new_value"].ToString() : "";
                            string status = elem.ContainsKey("status")
                                ? elem["status"].ToString() : "";
                            string error = elem.ContainsKey("error")
                                ? elem["error"].ToString() : "";
                            md.AppendLine($"| {elemId} | {oldVal} | {newVal} | {status} | {error} |");
                        }
                    }
                    md.AppendLine();
                }

                // Counts
                md.AppendLine("## Summary");
                md.AppendLine();
                md.AppendLine($"- Preview count: {(data.ContainsKey("preview_count") ? data["preview_count"] : 0)}");
                md.AppendLine($"- Success count: {(data.ContainsKey("success_count") ? data["success_count"] : 0)}");
                md.AppendLine($"- Skipped count: {(data.ContainsKey("skipped_count") ? data["skipped_count"] : 0)}");
                md.AppendLine($"- Failed count: {(data.ContainsKey("failed_count") ? data["failed_count"] : 0)}");

                if (capResult.Warnings.Count > 0)
                {
                    md.AppendLine();
                    md.AppendLine("## Warnings");
                    foreach (var w in capResult.Warnings)
                        md.AppendLine($"- {w}");
                }

                if (capResult.Errors.Count > 0)
                {
                    md.AppendLine();
                    md.AppendLine("## Errors");
                    foreach (var e in capResult.Errors)
                        md.AppendLine($"- {e}");
                }

                File.WriteAllText(
                    Path.Combine(runDir, "result_summary.md"),
                    md.ToString());

                return runDir;
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"PersistSetParameterValueEvidence failed: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// For apply runs initiated from preview approval, copy the preview run's
        /// preview.json into the apply run folder as linked_preview.json and write
        /// linked_preview_metadata.json with reconciliation fields. Never throws for
        /// a missing preview.json — records copy_status: missing_preview_json instead,
        /// so a successful model update is not undone by an evidence-linking failure.
        /// Returns the copy status ("copied" | "missing_preview_json").
        /// </summary>
        private static string WriteLinkedPreviewArtifacts(
            string applyRunDir,
            Dictionary<string, object> data,
            out bool targetIdsMatch,
            out bool linkedPreviewCopied)
        {
            targetIdsMatch = false;
            linkedPreviewCopied = false;

            string previewPath = data.ContainsKey("preview_evidence_path")
                ? (data["preview_evidence_path"]?.ToString() ?? "") : "";

            var previewedIds = ToLongList(
                data.ContainsKey("element_ids_previewed") ? data["element_ids_previewed"] : null);

            var appliedIds = new List<long>();
            if (data.ContainsKey("elements") &&
                data["elements"] is List<Dictionary<string, object>> elements)
            {
                foreach (var elem in elements)
                {
                    bool ok = elem.ContainsKey("status") &&
                        string.Equals(elem["status"]?.ToString(), "success",
                            StringComparison.OrdinalIgnoreCase);
                    if (ok && elem.ContainsKey("element_id"))
                    {
                        try { appliedIds.Add(Convert.ToInt64(elem["element_id"])); }
                        catch { /* skip unparseable id */ }
                    }
                }
            }

            targetIdsMatch = previewedIds.Count > 0 &&
                new HashSet<long>(previewedIds).SetEquals(appliedIds);

            string copyStatus;
            string srcPreviewJson = string.IsNullOrEmpty(previewPath)
                ? null : Path.Combine(previewPath, "preview.json");
            if (srcPreviewJson != null && File.Exists(srcPreviewJson))
            {
                try
                {
                    File.Copy(srcPreviewJson,
                        Path.Combine(applyRunDir, "linked_preview.json"), true);
                    copyStatus = "copied";
                    linkedPreviewCopied = true;
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"linked_preview.json copy failed: {ex.Message}");
                    copyStatus = "copy_failed";
                }
            }
            else
            {
                copyStatus = "missing_preview_json";
            }

            var metadata = new Dictionary<string, object>
            {
                { "preview_evidence_path", previewPath },
                { "copied_at", DateTime.UtcNow.ToString("o") },
                { "source_preview_run_id", string.IsNullOrEmpty(previewPath)
                    ? "" : Path.GetFileName(previewPath.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)) },
                { "apply_run_id", Path.GetFileName(applyRunDir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)) },
                { "element_ids_previewed", previewedIds },
                { "element_ids_applied", appliedIds },
                { "target_ids_match", targetIdsMatch },
                { "initiated_from", "preview_approval" },
                { "copy_status", copyStatus },
            };
            File.WriteAllText(
                Path.Combine(applyRunDir, "linked_preview_metadata.json"),
                JsonConvert.SerializeObject(metadata, Formatting.Indented));

            return copyStatus;
        }

        /// <summary>
        /// Coerce a heterogeneous value (List&lt;long&gt;, List&lt;object&gt;, etc.)
        /// into a List&lt;long&gt;, skipping any element that cannot be parsed.
        /// </summary>
        private static List<long> ToLongList(object value)
        {
            var result = new List<long>();
            if (value is System.Collections.IEnumerable seq && !(value is string))
            {
                foreach (var item in seq)
                {
                    try { result.Add(Convert.ToInt64(item)); }
                    catch { /* skip unparseable id */ }
                }
            }
            return result;
        }

        /// <summary>
        /// Execute a parameter schema plan: reads the latest plan JSON,
        /// dispatches category_parameter_schema one category at a time,
        /// writes one export per category, and produces a manifest.
        /// </summary>
        private Result ExecuteParameterSchemaPlan(
            Document doc,
            PromptDispatcher dispatcher,
            string originalPrompt,
            Dictionary<string, object> planOptions)
        {
            bool isResume = planOptions.ContainsKey("is_resume") && (bool)planOptions["is_resume"];
            bool priorityOnly = planOptions.ContainsKey("priority_only") && (bool)planOptions["priority_only"];
            int maxCategories = planOptions.ContainsKey("max_categories")
                ? Convert.ToInt32(planOptions["max_categories"]) : 0;

            // Locate latest plan JSON
            string localAppData = Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData);
            string plansDir = Path.Combine(localAppData, "Axiom", "inventory_plans");
            string exportsDir = Path.Combine(localAppData, "Axiom", "inventory_exports");
            Directory.CreateDirectory(exportsDir);

            // NOTE: Environment.CurrentDirectory inside Revit resolves to
            // C:\Program Files\Autodesk\Revit, not the repo root.
            // The LocalAppData handoff path is the supported Revit plan source.
            // Repo artifacts are only reachable from the CLI, not from Revit.

            List<Dictionary<string, object>> planJobs = null;
            string planId = "";
            var searchedPaths = new List<string>();

            // Priority 1: LocalAppData handoff locations (written by inventory-plan CLI)
            string[] directPaths = {
                Path.Combine(plansDir, "latest", "parameter_schema_plan.json"),
                Path.Combine(plansDir, "parameter_schema_plan.json"),
            };
            foreach (var dp in directPaths)
            {
                searchedPaths.Add(dp);
                if (File.Exists(dp))
                {
                    planJobs = TryLoadPlanJobs(dp, out planId);
                    if (planJobs != null) break;
                }
            }

            // Priority 2: Subdirectories under LocalAppData (sorted newest-first)
            if (planJobs == null)
            {
                string[] planSearchDirs = { plansDir };
                foreach (var searchDir in planSearchDirs)
                {
                    searchedPaths.Add(searchDir + "\\<latest>\\parameter_schema_plan.json");
                    if (!Directory.Exists(searchDir)) continue;
                    var planDirs = Directory.GetDirectories(searchDir);
                    Array.Sort(planDirs);
                    Array.Reverse(planDirs);
                    foreach (var pd in planDirs)
                    {
                        string planFile = Path.Combine(pd, "parameter_schema_plan.json");
                        if (File.Exists(planFile))
                        {
                            planJobs = TryLoadPlanJobs(planFile, out planId);
                            if (planJobs != null) break;
                        }
                    }
                    if (planJobs != null) break;
                }
            }

            if (planJobs == null || planJobs.Count == 0)
            {
                string pathsList = string.Join("\n", searchedPaths.Select(p => "  - " + p));
                TaskDialog.Show(
                    "Axiom - Parameter Schema Plan",
                    "No parameter_schema_plan.json found.\n\n" +
                    "Searched:\n" + pathsList + "\n\n" +
                    "To create a plan:\n" +
                    "1. Run: \"Run InventoryModel\" or \"Run InventoryModel schema\"\n" +
                    "2. Import: axiom inventory-import --file <export.json>\n" +
                    "3. Plan: axiom inventory-plan --file <summary.json> --mode parameter-schema\n" +
                    "   (writes handoff copy to LocalAppData for Revit pickup)\n\n" +
                    "Then retry: \"Run InventoryModel parameter schema plan\"");
                return Result.Failed;
            }

            // Filter by priority if requested
            string[] priorityCats = {
                "Walls", "Doors", "Windows", "Floors", "Rooms", "Views", "Sheets",
                "Levels", "Grids", "Ducts", "Pipes", "Mechanical Equipment",
                "Plumbing Fixtures", "Lighting Fixtures", "Electrical Fixtures",
                "Ceilings", "Columns", "Stairs", "Railings", "Furniture"
            };
            var prioritySet = new HashSet<string>(
                priorityCats, StringComparer.OrdinalIgnoreCase);

            if (priorityOnly)
            {
                planJobs = planJobs.FindAll(j =>
                {
                    var cats = j.ContainsKey("categories")
                        ? JsonConvert.DeserializeObject<List<string>>(j["categories"].ToString())
                        : new List<string>();
                    return cats.Count > 0 && prioritySet.Contains(cats[0]);
                });
            }

            // Apply max limit
            if (maxCategories > 0 && planJobs.Count > maxCategories)
                planJobs = planJobs.GetRange(0, maxCategories);

            // Resume: check latest manifest for already-completed categories
            var completedCategories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (isResume)
            {
                var manifestFiles = Directory.Exists(exportsDir)
                    ? Directory.GetFiles(exportsDir, "parameter_schema_manifest_*.json")
                    : new string[0];
                Array.Sort(manifestFiles);
                Array.Reverse(manifestFiles);
                if (manifestFiles.Length > 0)
                {
                    try
                    {
                        string manifestJson = File.ReadAllText(manifestFiles[0]);
                        var manifest = JsonConvert.DeserializeObject<Dictionary<string, object>>(manifestJson);
                        if (manifest != null && manifest.ContainsKey("exports"))
                        {
                            var exports = JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(
                                manifest["exports"].ToString());
                            foreach (var exp in exports)
                            {
                                if (exp.ContainsKey("status") && exp["status"].ToString() == "success"
                                    && exp.ContainsKey("category"))
                                {
                                    completedCategories.Add(exp["category"].ToString());
                                }
                            }
                        }
                    }
                    catch { /* ignore malformed manifest */ }
                }
            }

            // Categories that should be skipped (not real element categories)
            var skipCategories = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                "(No Category)", "No Category", "<Unnamed>",
            };

            // Execute category-by-category using structured dispatch
            var sw = System.Diagnostics.Stopwatch.StartNew();
            string startedAt = DateTime.UtcNow.ToString("o");
            var exportEntries = new List<Dictionary<string, object>>();
            int completed = 0;
            int failed = 0;
            int skipped = 0;

            foreach (var job in planJobs)
            {
                var cats = job.ContainsKey("categories")
                    ? JsonConvert.DeserializeObject<List<string>>(job["categories"].ToString())
                    : new List<string>();
                string category = cats.Count > 0 ? cats[0] : "";
                if (string.IsNullOrEmpty(category)) continue;

                string catPrompt = $"Run InventoryModel for {category} parameter schema";

                // Skip non-executable categories
                if (skipCategories.Contains(category))
                {
                    exportEntries.Add(new Dictionary<string, object>
                    {
                        { "category", category },
                        { "prompt", catPrompt },
                        { "status", "skipped_unsupported" },
                        { "export_path", "" },
                        { "error_message", $"Category '{category}' is not a valid element category" },
                        { "duration_ms", 0 },
                    });
                    skipped++;
                    continue;
                }

                // Skip already completed (resume mode)
                if (completedCategories.Contains(category))
                {
                    exportEntries.Add(new Dictionary<string, object>
                    {
                        { "category", category },
                        { "prompt", catPrompt },
                        { "status", "skipped_resume" },
                        { "export_path", "" },
                        { "error_message", "Already completed in previous run" },
                        { "duration_ms", 0 },
                    });
                    skipped++;
                    continue;
                }

                // Structured dispatch: bypass NLP, call capability directly
                var catSw = System.Diagnostics.Stopwatch.StartNew();

                try
                {
                    var catResult = dispatcher.DispatchCategoryParameterSchema(doc, category);
                    catSw.Stop();

                    if (catResult.Success && catResult.CapabilityResult != null)
                    {
                        var catData = catResult.CapabilityResult.OutputData;

                        // Inject traceability
                        catData["raw_prompt"] = catPrompt;
                        catData["resolved_capability"] = "InventoryModel";
                        catData["result_class"] = catResult.CapabilityResult.Status == "SUCCESS" ? "success" : "failure";
                        catData["source"] = "parameter_schema_plan";
                        catData["plan_id"] = planId;
                        try { catData["active_view"] = doc.ActiveView?.Name ?? ""; }
                        catch { catData["active_view"] = ""; }

                        string exportPath = PersistInventoryJson(
                            catResult.CapabilityResult, doc.Title, category);

                        exportEntries.Add(new Dictionary<string, object>
                        {
                            { "category", category },
                            { "prompt", catPrompt },
                            { "status", "success" },
                            { "export_path", exportPath ?? "" },
                            { "error_message", "" },
                            { "duration_ms", catSw.ElapsedMilliseconds },
                        });
                        completed++;
                    }
                    else
                    {
                        // Distinguish failure reasons
                        string errorMsg = catResult.Message ?? "Dispatch failed";
                        string failStatus = "failed";
                        if (catResult.CapabilityResult != null &&
                            catResult.CapabilityResult.OutputData.ContainsKey("element_count") &&
                            Convert.ToInt32(catResult.CapabilityResult.OutputData["element_count"]) == 0)
                        {
                            failStatus = "skipped_no_elements";
                            skipped++;
                        }
                        else
                        {
                            failed++;
                        }

                        exportEntries.Add(new Dictionary<string, object>
                        {
                            { "category", category },
                            { "prompt", catPrompt },
                            { "status", failStatus },
                            { "export_path", "" },
                            { "error_message", errorMsg },
                            { "duration_ms", catSw.ElapsedMilliseconds },
                        });
                    }
                }
                catch (Exception ex)
                {
                    catSw.Stop();
                    exportEntries.Add(new Dictionary<string, object>
                    {
                        { "category", category },
                        { "prompt", catPrompt },
                        { "status", "failed" },
                        { "export_path", "" },
                        { "error_message", ex.Message },
                        { "duration_ms", catSw.ElapsedMilliseconds },
                    });
                    failed++;
                    // Continue to next category
                }
            }

            sw.Stop();

            // Write manifest
            string manifestTimestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
            string manifestPath = Path.Combine(exportsDir,
                $"parameter_schema_manifest_{manifestTimestamp}.json");
            var manifestData = new Dictionary<string, object>
            {
                { "source_model", doc.Title ?? "" },
                { "run_id", $"plan_{manifestTimestamp}" },
                { "plan_id", planId },
                { "started_at", startedAt },
                { "completed_at", DateTime.UtcNow.ToString("o") },
                { "total_categories", planJobs.Count },
                { "completed_categories", completed },
                { "failed_categories", failed },
                { "skipped_categories", skipped },
                { "raw_prompt", originalPrompt },
                { "is_resume", isResume },
                { "priority_only", priorityOnly },
                { "max_categories", maxCategories },
                { "duration_ms", sw.ElapsedMilliseconds },
                { "exports", exportEntries },
            };

            try
            {
                var serializer = JsonSerializer.Create(
                    new JsonSerializerSettings { Formatting = Formatting.Indented });
                using (var msw = new StreamWriter(manifestPath, false,
                    System.Text.Encoding.UTF8))
                using (var mjw = new JsonTextWriter(msw))
                {
                    serializer.Serialize(mjw, manifestData);
                }
            }
            catch (Exception manifestEx)
            {
                // Manifest write failed — warn in dialog instead of silently continuing
                manifestPath = $"WRITE FAILED: {manifestEx.Message}";
            }

            // Show results dialog
            bool manifestExists = File.Exists(manifestPath);
            string dialogBody = $"Parameter Schema Plan Execution\n\n" +
                $"Categories completed: {completed}\n" +
                $"Categories failed: {failed}\n" +
                $"Categories skipped: {skipped}\n" +
                $"Total duration: {sw.ElapsedMilliseconds}ms\n\n" +
                (manifestExists
                    ? $"Manifest: {manifestPath}\n\n"
                    : $"WARNING: Manifest write failed — {manifestPath}\n\n") +
                $"Next steps:\n" +
                $"axiom inventory-import-batch --dir \"{exportsDir}\" " +
                $"--scan-mode category_parameter_schema\n\n" +
                $"Or with manifest:\n" +
                $"axiom inventory-import-batch --manifest \"{manifestPath}\"";

            if (failed > 0)
            {
                dialogBody += $"\n\nTo retry failed categories:\n" +
                    $"Run InventoryModel parameter schema plan resume";
            }

            TaskDialog.Show(
                $"Axiom - Parameter Schema Plan ({completed}/{planJobs.Count})",
                dialogBody);

            return Result.Succeeded;
        }

        /// <summary>
        /// Try to load plan jobs from a JSON file. Returns null if malformed.
        /// </summary>
        private static List<Dictionary<string, object>> TryLoadPlanJobs(
            string planFile, out string planId)
        {
            planId = "";
            try
            {
                string planJson = File.ReadAllText(planFile);
                var plan = JsonConvert.DeserializeObject<Dictionary<string, object>>(planJson);
                if (plan != null && plan.ContainsKey("jobs"))
                {
                    var jobsRaw = JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(
                        plan["jobs"].ToString());
                    if (jobsRaw != null && jobsRaw.Count > 0)
                    {
                        planId = plan.ContainsKey("run_id") ? plan["run_id"].ToString() : "";
                        return jobsRaw;
                    }
                }
            }
            catch { /* skip malformed plan files */ }
            return null;
        }

        /// <summary>Sequence counter for unique export filenames within a session.</summary>
        private static int _exportSequence = 0;

        /// <summary>
        /// Sanitize a category name into a safe filesystem slug.
        /// Replaces spaces with underscores, removes invalid path chars,
        /// strips parentheses, and lowercases.
        /// </summary>
        private static string CategorySlug(string category)
        {
            if (string.IsNullOrWhiteSpace(category)) return "unknown";
            var slug = category.Trim().ToLowerInvariant()
                .Replace(" ", "_")
                .Replace("(", "").Replace(")", "");
            // Remove any remaining invalid filename chars
            foreach (char c in Path.GetInvalidFileNameChars())
                slug = slug.Replace(c.ToString(), "");
            if (slug.Length > 60) slug = slug.Substring(0, 60);
            return string.IsNullOrEmpty(slug) ? "unknown" : slug;
        }

        /// <summary>
        /// Write inventory results to a JSON file for the Python persistence pipeline.
        /// Returns the full file path on success, or null on failure.
        /// Output: %LOCALAPPDATA%\Axiom\inventory_exports\inv_YYYYMMDD_HHmmss_fff_NNN_slug.json
        /// Uses streaming serialization to avoid building huge in-memory strings.
        /// </summary>
        private static string PersistInventoryJson(
            Axiom.Core.Capabilities.CapabilityResult capResult,
            string docTitle,
            string category = null)
        {
            try
            {
                string localAppData = Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData);
                string exportDir = Path.Combine(localAppData, "Axiom", "inventory_exports");
                Directory.CreateDirectory(exportDir);

                int seq = System.Threading.Interlocked.Increment(ref _exportSequence);
                string slug = CategorySlug(
                    category
                    ?? (capResult.OutputData.ContainsKey("object_category")
                        ? capResult.OutputData["object_category"]?.ToString()
                        : null)
                    ?? "export");
                string runId = "inv_" + DateTime.Now.ToString("yyyyMMdd_HHmmss_fff")
                    + $"_{seq:D3}_{slug}";
                string filePath = Path.Combine(exportDir, runId + ".json");

                var exportData = new Dictionary<string, object>
                {
                    { "run_id", runId },
                    { "source_model", docTitle ?? "" },
                    { "timestamp", DateTime.UtcNow.ToString("o") },
                    { "duration_ms", capResult.DurationMs },
                    { "scan_mode", capResult.OutputData.ContainsKey("scan_mode")
                        ? capResult.OutputData["scan_mode"] : "summary" },
                    { "instance_count", capResult.OutputData.ContainsKey("instance_count")
                        ? capResult.OutputData["instance_count"] : 0 },
                    { "element_count", capResult.OutputData.ContainsKey("element_count")
                        ? capResult.OutputData["element_count"] : 0 },
                    { "type_count", capResult.OutputData.ContainsKey("type_count")
                        ? capResult.OutputData["type_count"] : 0 },
                    { "parameter_count", capResult.OutputData.ContainsKey("parameter_count")
                        ? capResult.OutputData["parameter_count"] : 0 },
                    { "error_count", capResult.OutputData.ContainsKey("error_count")
                        ? capResult.OutputData["error_count"] : 0 },
                    { "category_counts", capResult.OutputData.ContainsKey("category_counts")
                        ? capResult.OutputData["category_counts"]
                        : new Dictionary<string, int>() },
                };

                // Include object_category if present
                if (capResult.OutputData.ContainsKey("object_category"))
                    exportData["object_category"] = capResult.OutputData["object_category"];

                // Prompt traceability fields
                string[] traceFields = { "raw_prompt", "resolved_capability", "result_class", "source", "active_view" };
                foreach (var tf in traceFields)
                {
                    if (capResult.OutputData.ContainsKey(tf))
                        exportData[tf] = capResult.OutputData[tf];
                }

                // Parameter schema mode: write parameter_definitions instead of elements
                if (capResult.OutputData.ContainsKey("parameter_definitions"))
                {
                    exportData["parameter_definitions"] = capResult.OutputData["parameter_definitions"];
                    exportData["parameter_definition_count"] = capResult.OutputData.ContainsKey("parameter_definition_count")
                        ? capResult.OutputData["parameter_definition_count"] : 0;
                }
                else
                {
                    exportData["elements"] = capResult.OutputData.ContainsKey("elements")
                        ? capResult.OutputData["elements"] : new List<object>();
                }

                // Use streaming write to avoid building a huge string in memory
                var serializer = JsonSerializer.Create(
                    new JsonSerializerSettings { Formatting = Formatting.Indented });
                using (var sw = new StreamWriter(filePath, false,
                    System.Text.Encoding.UTF8))
                using (var jw = new JsonTextWriter(sw))
                {
                    serializer.Serialize(jw, exportData);
                }

                return filePath;
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine(
                    $"PersistInventoryJson failed: {ex.Message}");
                return null;
            }
        }
    }
}

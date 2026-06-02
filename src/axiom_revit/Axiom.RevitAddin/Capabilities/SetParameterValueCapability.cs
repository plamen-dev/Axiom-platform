using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using Autodesk.Revit.DB;
using Axiom.Core.Capabilities;
using Axiom.Core.Models;
using Axiom.RevitAddin.Services;
using Newtonsoft.Json;

namespace Axiom.RevitAddin.Capabilities
{
    /// <summary>
    /// Capability for constrained text parameter edits.
    ///
    /// v0 constraints:
    /// - Text instance parameters only
    /// - Category-constrained (no whole-model edits)
    /// - Hard cap: 5 elements
    /// - Preview by default (no model modification)
    /// - Apply requires explicit mode
    /// - Active view only by default
    /// </summary>
    public class SetParameterValueCapability : IAxiomCapability
    {
        private const int MaxElementCap = 5;

        public string Name => "SetParameterValue";

        public string Description =>
            "Sets a text parameter value on a constrained set of elements " +
            "within a single category. Preview mode by default.";

        public Type ParameterType => typeof(SetParameterValueParameters);

        public CapabilityResult Execute(Document doc, string argsJson, bool simulate)
        {
            var sw = Stopwatch.StartNew();
            var result = new CapabilityResult();

            SetParameterValueParameters parameters;
            try
            {
                parameters = JsonConvert.DeserializeObject<SetParameterValueParameters>(argsJson);
            }
            catch (Exception ex)
            {
                result.Status = "FAILED";
                result.Errors.Add($"Invalid parameters JSON: {ex.Message}");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // --- Validation ---

            if (string.IsNullOrWhiteSpace(parameters.Category))
            {
                result.Status = "FAILED";
                result.Errors.Add("Category is required. Whole-model edits are not allowed.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            if (string.IsNullOrWhiteSpace(parameters.ParameterName))
            {
                result.Status = "FAILED";
                result.Errors.Add("ParameterName is required.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            if (parameters.Value == null)
            {
                result.Status = "FAILED";
                result.Errors.Add("Value is required.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            if (parameters.ElementCount <= 0)
            {
                result.Status = "FAILED";
                result.Errors.Add("ElementCount must be greater than 0.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            if (parameters.ElementCount > MaxElementCap)
            {
                result.Status = "FAILED";
                result.Errors.Add(
                    $"ElementCount {parameters.ElementCount} exceeds v0 cap of {MaxElementCap}.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            bool isPreview = string.IsNullOrEmpty(parameters.Mode) ||
                string.Equals(parameters.Mode, "preview", StringComparison.OrdinalIgnoreCase);

            // Force preview when simulate flag is set
            if (simulate)
                isPreview = true;

            // --- Collect elements ---
            var service = new ParameterEditService();
            bool targetedByIds = parameters.ElementIds != null && parameters.ElementIds.Count > 0;
            List<Element> elements;
            try
            {
                if (targetedByIds)
                {
                    // Interactive apply: target exactly the previewed element IDs.
                    // Never recollect by category — this guarantees Apply edits
                    // the same elements the user approved in the preview.
                    if (parameters.ElementIds.Count > MaxElementCap)
                    {
                        result.Status = "FAILED";
                        result.Errors.Add(
                            $"ElementIds count {parameters.ElementIds.Count} exceeds v0 cap of {MaxElementCap}.");
                        result.DurationMs = sw.ElapsedMilliseconds;
                        return result;
                    }

                    List<long> missingIds;
                    elements = service.CollectElementsByIds(doc, parameters.ElementIds, out missingIds);

                    if (missingIds.Count > 0)
                    {
                        // Block Apply: one or more previewed elements can no
                        // longer be resolved (deleted or changed since preview).
                        result.Status = "FAILED";
                        result.Errors.Add(
                            $"Apply blocked: {missingIds.Count} previewed element(s) no longer resolve by ID " +
                            $"[{string.Join(", ", missingIds)}]. The model may have changed since preview. " +
                            "Re-run the preview before applying.");
                        result.DurationMs = sw.ElapsedMilliseconds;
                        return result;
                    }
                }
                else
                {
                    elements = service.CollectElements(
                        doc,
                        parameters.Category,
                        parameters.ElementCount,
                        parameters.ActiveViewOnly);
                }
            }
            catch (Exception ex)
            {
                result.Status = "FAILED";
                result.Errors.Add($"Element collection failed: {ex.Message}");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            if (elements.Count == 0)
            {
                result.Status = "FAILED";
                result.Errors.Add(
                    $"No elements found for category '{parameters.Category}'" +
                    (parameters.ActiveViewOnly ? " in active view." : "."));
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // --- Execute preview or apply ---
            List<ParameterEditService.ElementEditResult> editResults;

            if (isPreview)
            {
                editResults = service.Preview(elements, parameters.ParameterName, parameters.Value);
                result.Status = "SUCCESS";
                result.OutputData["mode"] = "preview";
                result.OutputData["model_modified"] = false;
            }
            else
            {
                editResults = service.Apply(elements, parameters.ParameterName, parameters.Value);

                int successCount = editResults.Count(r => r.Status == "success");
                int failedCount = editResults.Count(r => r.Status == "failed");

                if (failedCount > 0 && successCount == 0)
                {
                    result.Status = "FAILED";
                    result.Errors.Add(
                        $"All {failedCount} element(s) failed to update.");
                }
                else if (failedCount > 0)
                {
                    result.Status = "SUCCESS";
                    result.Warnings.Add(
                        $"{failedCount} of {editResults.Count} element(s) failed.");
                }
                else
                {
                    result.Status = "SUCCESS";
                }

                result.OutputData["mode"] = "apply";
                result.OutputData["model_modified"] = successCount > 0;
                result.CreatedIds = editResults
                    .Where(r => r.Status == "success")
                    .Select(r => r.ElementId.ToString())
                    .ToList();
            }

            // --- Build output data ---
            var elementData = new List<Dictionary<string, object>>();
            foreach (var er in editResults)
            {
                var d = new Dictionary<string, object>
                {
                    { "element_id", er.ElementId },
                    { "category", er.Category },
                    { "old_value", er.OldValue },
                    { "new_value", er.NewValue },
                    { "status", er.Status }
                };
                if (er.ErrorMessage != null)
                    d["error"] = er.ErrorMessage;
                elementData.Add(d);
            }

            result.OutputData["category"] = parameters.Category;
            result.OutputData["parameter_name"] = parameters.ParameterName;
            result.OutputData["value"] = parameters.Value;
            result.OutputData["element_count"] = elements.Count;
            result.OutputData["requested_count"] = parameters.ElementCount;
            result.OutputData["active_view_only"] = parameters.ActiveViewOnly;
            result.OutputData["raw_prompt"] = parameters.RawPrompt ?? "";
            result.OutputData["targeted_by_ids"] = targetedByIds;
            result.OutputData["elements"] = elementData;

            int previewCount = editResults.Count(r => r.Status == "preview");
            int applySuccessCount = editResults.Count(r => r.Status == "success");
            int skippedCount = editResults.Count(r => r.Status == "skipped");
            int applyFailedCount = editResults.Count(r => r.Status == "failed");

            result.OutputData["preview_count"] = previewCount;
            result.OutputData["success_count"] = applySuccessCount;
            result.OutputData["skipped_count"] = skippedCount;
            result.OutputData["failed_count"] = applyFailedCount;

            result.DurationMs = sw.ElapsedMilliseconds;
            return result;
        }
    }
}

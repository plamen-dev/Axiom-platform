using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Axiom.Core.Bridge;
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

            // Check if this is InventoryModel (read-only, no view restriction)
            var preResolve = dispatcher.Resolve(promptText);
            bool isInventory = preResolve.Success &&
                               preResolve.CapabilityName == "InventoryModel";

            // Enforce plan view only for model-modifying capabilities
            if (!isInventory)
            {
                View view = doc.ActiveView;
                if (!(view is ViewPlan) || view.IsTemplate)
                {
                    TaskDialog.Show(
                        "Axiom",
                        "This capability requires a plan view.\n\n" +
                        "Open a Floor Plan or Ceiling Plan and try again.\n" +
                        "(InventoryModel can run from any view.)");
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
                            catResult.CapabilityResult, doc.Title);

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

        /// <summary>
        /// Write inventory results to a JSON file for the Python persistence pipeline.
        /// Returns the full file path on success, or null on failure.
        /// Output: %LOCALAPPDATA%\Axiom\inventory_exports\inv_YYYYMMDD_HHmmss.json
        /// Uses streaming serialization to avoid building huge in-memory strings.
        /// </summary>
        private static string PersistInventoryJson(
            Axiom.Core.Capabilities.CapabilityResult capResult,
            string docTitle)
        {
            try
            {
                string localAppData = Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData);
                string exportDir = Path.Combine(localAppData, "Axiom", "inventory_exports");
                Directory.CreateDirectory(exportDir);

                string runId = "inv_" + DateTime.Now.ToString("yyyyMMdd_HHmmss");
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

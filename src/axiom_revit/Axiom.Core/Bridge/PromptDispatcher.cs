using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using Axiom.Core.Capabilities;
using Newtonsoft.Json;

namespace Axiom.Core.Bridge
{
    /// <summary>
    /// Routes free-form prompt text to registered capabilities.
    ///
    /// This is the C# equivalent of the Python prompt_resolver:
    /// parses text, identifies capability, builds args JSON, and
    /// calls the capability directly (no pipe roundtrip needed
    /// when running inside Revit).
    /// </summary>
    public class PromptDispatcher
    {
        private readonly ToolRegistry _registry;

        public PromptDispatcher(ToolRegistry registry)
        {
            _registry = registry;
        }

        /// <summary>
        /// Resolve a prompt without executing. Returns a result indicating
        /// whether the prompt resolved, needs clarification, or failed.
        /// No capability is executed — use this for pre-checks.
        /// </summary>
        public PromptDispatchResult Resolve(string promptText)
        {
            if (string.IsNullOrWhiteSpace(promptText))
            {
                return PromptDispatchResult.Fail("Empty prompt. Please enter a request.");
            }

            string lower = promptText.ToLowerInvariant().Trim();
            string capabilityName = ResolveCapability(lower);

            if (capabilityName == null)
            {
                string clarification = CheckGridClarification(lower);
                if (clarification != null)
                    return PromptDispatchResult.Clarification(clarification);

                string levelClarification = CheckLevelClarification(lower);
                if (levelClarification != null)
                    return PromptDispatchResult.Clarification(levelClarification);

                return PromptDispatchResult.Fail(
                    "Could not resolve prompt to a known capability.\n\n" +
                    "Currently supported:\n" +
                    "  - Grid creation (e.g. \"Create 10 vertical gridlines, " +
                    "50 ft long, spaced 10 ft apart\")\n" +
                    "  - Level creation (e.g. \"Create 5 levels spaced 12 ft apart\")\n" +
                    "  - Model inventory (e.g. \"Run InventoryModel\")\n" +
                    "  - Parameter edit (e.g. \"Set Comments to Axiom test for 3 Walls\")\n\n" +
                    "Unsupported prompts will be available in future updates.");
            }

            // Check for grid spacing ambiguities before accepting resolution
            if (capabilityName == "CreateGrids")
            {
                string spacingClarification = CheckGridSpacingClarification(lower, promptText);
                if (spacingClarification != null)
                    return PromptDispatchResult.Clarification(spacingClarification);
            }

            return new PromptDispatchResult
            {
                Success = true,
                CapabilityName = capabilityName,
                Message = $"Resolved to: {capabilityName}"
            };
        }

        /// <summary>
        /// Dispatch a free-text prompt to the appropriate capability.
        /// Resolves the prompt and executes the matched capability.
        /// </summary>
        public PromptDispatchResult Dispatch(
            Autodesk.Revit.DB.Document doc,
            string promptText)
        {
            if (string.IsNullOrWhiteSpace(promptText))
            {
                return PromptDispatchResult.Fail("Empty prompt. Please enter a request.");
            }

            string lower = promptText.ToLowerInvariant().Trim();

            // Attempt to resolve to a capability
            string capabilityName = ResolveCapability(lower);

            if (capabilityName == null)
            {
                // Check for ambiguous rows/columns prompts
                string clarification = CheckGridClarification(lower);
                if (clarification != null)
                {
                    return PromptDispatchResult.Clarification(clarification);
                }

                // Check for ambiguous floors/stories prompts
                string levelClarification = CheckLevelClarification(lower);
                if (levelClarification != null)
                {
                    return PromptDispatchResult.Clarification(levelClarification);
                }

                return PromptDispatchResult.Fail(
                    "Could not resolve prompt to a known capability.\n\n" +
                    "Currently supported:\n" +
                    "  - Grid creation (e.g. \"Create 10 vertical gridlines, " +
                    "50 ft long, spaced 10 ft apart\")\n" +
                    "  - Level creation (e.g. \"Create 5 levels spaced 12 ft apart\")\n" +
                    "  - Model inventory (e.g. \"Run InventoryModel\")\n" +
                    "  - Parameter edit (e.g. \"Set Comments to Axiom test for 3 Walls\")\n\n" +
                    "Unsupported prompts will be available in future updates.");
            }

            // Check for grid spacing ambiguities before executing
            if (capabilityName == "CreateGrids")
            {
                string spacingClarification = CheckGridSpacingClarification(lower, promptText);
                if (spacingClarification != null)
                    return PromptDispatchResult.Clarification(spacingClarification);
            }

            IAxiomCapability capability;
            if (!_registry.TryGet(capabilityName, out capability))
            {
                return PromptDispatchResult.Fail(
                    $"Capability not registered: {capabilityName}\n\n" +
                    "The capability was recognized but is not available in this build.");
            }

            // Block full inventory scan — crashes Revit on large models (BUG-014)
            if (capabilityName == "InventoryModel" &&
                (lower.Contains("full inventory") ||
                 lower.Contains("run full inventorymodel") ||
                 lower.Contains("full scan") ||
                 lower.Contains("complete inventory") ||
                 lower.Contains("full values")))
            {
                return new PromptDispatchResult
                {
                    Success = false,
                    CapabilityName = capabilityName,
                    Message =
                        "BLOCKED_UNSAFE: Full value extraction is disabled for live Revit sessions.\n" +
                        "Full element+parameter scans have caused Revit crashes on large models.\n\n" +
                        "Safe alternatives:\n" +
                        "  - \"Run InventoryModel\" (summary counts only)\n" +
                        "  - \"Run InventoryModel schema\" (parameter definitions, no values)\n" +
                        "  - \"Run InventoryModel sample values for Walls\" (constrained samples)\n" +
                        "  - \"Run InventoryModel for Walls\" (single category scan)\n\n" +
                        "Use schema discovery for whole-model learning."
                };
            }

            // Block whole-model sample values — crashed Revit 2027 (BUG-016)
            if (capabilityName == "InventoryModel" &&
                (lower.Contains("sample values") || lower.Contains("sample value")) &&
                !lower.Contains("inventory for ") &&
                !lower.Contains("inventory walls") && !lower.Contains("inventory doors") &&
                !lower.Contains("values for ") &&
                !lower.Contains("on level"))
            {
                // Check if any known category is mentioned
                bool hasCategoryConstraint = false;
                string[] knownCats = {
                    "walls", "doors", "windows", "floors", "roofs", "ceilings",
                    "columns", "beams", "stairs", "railings", "furniture",
                    "plumbing fixtures", "mechanical equipment", "electrical fixtures",
                    "lighting fixtures", "generic models", "duct systems", "ducts",
                    "pipe systems", "pipes", "rooms", "areas", "levels",
                    "views", "sheets"
                };
                foreach (var cat in knownCats)
                {
                    if (lower.Contains(cat))
                    {
                        hasCategoryConstraint = true;
                        break;
                    }
                }
                if (!hasCategoryConstraint)
                {
                    return new PromptDispatchResult
                    {
                        Success = false,
                        CapabilityName = capabilityName,
                        Message =
                            "BLOCKED_UNSAFE: Whole-model value sampling is disabled for live Revit sessions.\n" +
                            "It crashed Revit 2027 due to expensive value accessors.\n\n" +
                            "Use constrained sample values instead:\n" +
                            "  - \"Run InventoryModel sample values for Walls\"\n" +
                            "  - \"Run InventoryModel sample values for Plumbing Fixtures\"\n" +
                            "  - \"Run InventoryModel sample values for Walls max 25\"\n" +
                            "  - \"Run InventoryModel sample values on Level 1 max 25\"\n\n" +
                            "For whole-model learning, use schema discovery:\n" +
                            "  - \"Run InventoryModel schema\""
                    };
                }
            }

            // Allow "parameter schema plan" prompts through — they execute
            // category-by-category, never whole-model.
            bool isParameterSchemaPlan = capabilityName == "InventoryModel" &&
                (lower.Contains("parameter schema plan") || lower.Contains("param schema plan"));

            // Block whole-model parameter schema — crashed Revit 2027 (BUG-017)
            if (capabilityName == "InventoryModel" && !isParameterSchemaPlan &&
                (lower.Contains("parameter schema") || lower.Contains("param schema")))
            {
                bool hasConstraint = false;
                string[] knownCats2 = {
                    "walls", "doors", "windows", "floors", "roofs", "ceilings",
                    "columns", "beams", "stairs", "railings", "furniture",
                    "plumbing fixtures", "mechanical equipment", "electrical fixtures",
                    "lighting fixtures", "generic models", "duct systems", "ducts",
                    "pipe systems", "pipes", "rooms", "areas", "levels",
                    "views", "sheets"
                };
                foreach (var cat in knownCats2)
                {
                    if (lower.Contains(cat))
                    {
                        hasConstraint = true;
                        break;
                    }
                }
                if (!hasConstraint && !lower.Contains("on level") &&
                    !lower.Contains("inventory for ") && !lower.Contains("schema for "))
                {
                    return new PromptDispatchResult
                    {
                        Success = false,
                        CapabilityName = capabilityName,
                        Message =
                            "BLOCKED_UNSAFE: Whole-model parameter schema discovery is disabled for live Revit sessions.\n" +
                            "It crashed Revit 2027 on large models.\n\n" +
                            "Use category or level-constrained parameter schema:\n" +
                            "  - \"Run InventoryModel for Walls parameter schema\"\n" +
                            "  - \"Run InventoryModel for Ceilings parameter schema\"\n" +
                            "  - \"Run InventoryModel parameter schema on Level 1\"\n\n" +
                            "For planned multi-category extraction:\n" +
                            "  - \"Run InventoryModel parameter schema plan\"\n" +
                            "  - \"Run InventoryModel parameter schema plan max 10\"\n\n" +
                            "For whole-model element inventory (no parameters):\n" +
                            "  - \"Run InventoryModel schema\" (object_schema — validated safe)"
                    };
                }
            }

            // Parameter schema plan: return a special result that PromptCommand handles
            if (isParameterSchemaPlan)
            {
                bool isResume = lower.Contains("resume");
                bool isPriorityOnly = lower.Contains("priority only") || lower.Contains("priority-only");
                int maxCategories = 0;
                var maxMatch = Regex.Match(lower, @"(?:max|limit|first|top)\s+(\d+)");
                if (maxMatch.Success)
                    maxCategories = int.Parse(maxMatch.Groups[1].Value);

                return new PromptDispatchResult
                {
                    Success = true,
                    CapabilityName = "InventoryModel",
                    Message = "PLAN_EXECUTION",
                    CapabilityResult = new Capabilities.CapabilityResult
                    {
                        Status = "PLAN_EXECUTION",
                        OutputData = new Dictionary<string, object>
                        {
                            { "is_plan_execution", true },
                            { "is_resume", isResume },
                            { "priority_only", isPriorityOnly },
                            { "max_categories", maxCategories },
                        }
                    }
                };
            }

            // Build args JSON from the prompt (pass original text for table parsing)
            string argsJson = capabilityName == "InventoryModel"
                ? BuildInventoryArgsJson(lower)
                : BuildArgsJson(lower, capabilityName, promptText);

            try
            {
                var result = capability.Execute(doc, argsJson, false);
                string successMessage;
                if (capabilityName == "InventoryModel" && result.Status == "SUCCESS")
                {
                    int elemCount = result.OutputData.ContainsKey("element_count")
                        ? Convert.ToInt32(result.OutputData["element_count"]) : 0;
                    int typeCount = result.OutputData.ContainsKey("type_count")
                        ? Convert.ToInt32(result.OutputData["type_count"]) : 0;
                    int paramCount = result.OutputData.ContainsKey("parameter_count")
                        ? Convert.ToInt32(result.OutputData["parameter_count"]) : 0;
                    string scanMode = result.OutputData.ContainsKey("scan_mode")
                        ? result.OutputData["scan_mode"].ToString() : "summary";
                    successMessage =
                        $"Capability: {capabilityName} ({scanMode})\n" +
                        $"Status: SUCCESS\n" +
                        $"Elements inventoried: {elemCount} instances, {typeCount} types\n" +
                        (paramCount > 0
                            ? $"Parameters inventoried: {paramCount}\n"
                            : "") +
                        $"Duration: {result.DurationMs}ms";
                }
                else if (result.Status == "SUCCESS")
                {
                    successMessage =
                        $"Capability: {capabilityName}\n" +
                        $"Status: SUCCESS\n" +
                        $"Created: {result.CreatedIds.Count} element(s)\n" +
                        $"Duration: {result.DurationMs}ms";
                }
                else
                {
                    successMessage = null;
                }

                return new PromptDispatchResult
                {
                    Success = result.Status == "SUCCESS",
                    CapabilityName = capabilityName,
                    CapabilityResult = result,
                    Message = successMessage ??
                        ($"Capability: {capabilityName}\n" +
                         $"Status: FAILED\n" +
                         $"Errors: {string.Join("; ", result.Errors)}")
                };
            }
            catch (Exception ex)
            {
                return PromptDispatchResult.Fail(
                    $"Capability: {capabilityName}\n" +
                    $"Execution failed: {ex.Message}");
            }
        }

        /// <summary>
        /// Execute a named capability with pre-built args JSON, bypassing
        /// prompt parsing. Used by the interactive SetParameterValue apply
        /// flow to re-execute the exact resolved request (same parameter,
        /// value, and element IDs) approved during preview — the user never
        /// has to retype the prompt. The caller owns transaction management.
        /// </summary>
        public PromptDispatchResult DispatchWithArgs(
            Autodesk.Revit.DB.Document doc,
            string capabilityName,
            string argsJson)
        {
            IAxiomCapability capability;
            if (!_registry.TryGet(capabilityName, out capability))
            {
                return PromptDispatchResult.Fail(
                    $"Capability not registered: {capabilityName}");
            }

            try
            {
                var result = capability.Execute(doc, argsJson, false);
                return new PromptDispatchResult
                {
                    Success = result.Status == "SUCCESS",
                    CapabilityName = capabilityName,
                    CapabilityResult = result,
                    Message = result.Status
                };
            }
            catch (Exception ex)
            {
                return PromptDispatchResult.Fail(
                    $"{capabilityName} execution error: {ex.Message}");
            }
        }

        /// <summary>
        /// Dispatch a structured category parameter schema request directly,
        /// bypassing NLP prompt parsing. Used by the plan execution queue
        /// to avoid fragile category name matching through the resolver.
        /// </summary>
        public PromptDispatchResult DispatchCategoryParameterSchema(
            Autodesk.Revit.DB.Document doc, string category)
        {
            IAxiomCapability capability;
            if (!_registry.TryGet("InventoryModel", out capability))
            {
                return PromptDispatchResult.Fail(
                    "InventoryModel capability not registered.");
            }

            var args = new Dictionary<string, object>
            {
                { "SummaryOnly", false },
                { "ParameterSchemaOnly", true },
                { "IncludeParameters", false },
                { "ScanMode", "category_parameter_schema" },
                { "CategoryFilter", new[] { category } },
            };

            string argsJson = JsonConvert.SerializeObject(args);

            try
            {
                var result = capability.Execute(doc, argsJson, false);

                int elemCount = result.OutputData.ContainsKey("element_count")
                    ? Convert.ToInt32(result.OutputData["element_count"]) : 0;
                int paramCount = result.OutputData.ContainsKey("parameter_count")
                    ? Convert.ToInt32(result.OutputData["parameter_count"]) : 0;

                return new PromptDispatchResult
                {
                    Success = result.Status == "SUCCESS",
                    CapabilityName = "InventoryModel",
                    CapabilityResult = result,
                    Message = result.Status == "SUCCESS"
                        ? $"Capability: InventoryModel (category_parameter_schema)\n" +
                          $"Category: {category}\n" +
                          $"Status: SUCCESS\n" +
                          $"Elements: {elemCount}, Parameters: {paramCount}\n" +
                          $"Duration: {result.DurationMs}ms"
                        : $"Capability: InventoryModel\n" +
                          $"Category: {category}\n" +
                          $"Status: FAILED\n" +
                          $"Errors: {string.Join("; ", result.Errors)}"
                };
            }
            catch (Exception ex)
            {
                return PromptDispatchResult.Fail(
                    $"Category: {category}\n" +
                    $"Execution failed: {ex.Message}");
            }
        }

        private string ResolveCapability(string lower)
        {
            // SetParameterValue: "set <param> to <value> for <N> <category>"
            // Must check before inventory to avoid false match on "set" + category
            if (lower.StartsWith("set ") || lower.StartsWith("apply set "))
            {
                // Must contain "to" and "for" with a count pattern
                if (System.Text.RegularExpressions.Regex.IsMatch(
                    lower, @"\bto\b.+\bfor\s+\w+\s+\w"))
                {
                    return "SetParameterValue";
                }
            }

            // Inventory keywords (checked first — read-only, unambiguous)
            string[] inventoryKeywords = {
                "run inventorymodel", "inventory model", "inventorymodel",
                "list all model elements", "scan model parameters",
                "extract model parameters", "model inventory",
                "inventory parameters", "run full inventorymodel",
                "full inventory", "inventory sample"
            };
            foreach (var kw in inventoryKeywords)
            {
                if (lower.Contains(kw))
                    return "InventoryModel";
            }

            // Category-scoped inventory: "inventory walls", "inventory for doors"
            if (lower.Contains("inventory") && !lower.Contains("grid") && !lower.Contains("level"))
                return "InventoryModel";

            // Grid keywords
            string[] gridKeywords = { "grid", "grids", "gridline", "gridlines" };
            bool hasGrid = false;
            foreach (var kw in gridKeywords)
            {
                if (lower.Contains(kw))
                    hasGrid = true;
            }

            // Level keywords (checked before grids since "level" is unambiguous,
            // but only if the prompt does NOT also contain grid keywords)
            string[] levelKeywords = { "level", "levels" };
            string[] createKeywords = { "create", "add", "make", "build", "generate" };
            bool hasLevel = false;
            bool hasCreate = false;
            foreach (var kw in levelKeywords)
            {
                if (lower.Contains(kw))
                    hasLevel = true;
            }
            foreach (var kw in createKeywords)
            {
                if (lower.Contains(kw))
                    hasCreate = true;
            }
            if (hasLevel && hasCreate && !hasGrid)
                return "CreateLevels";

            if (hasGrid)
                return "CreateGrids";

            return null;
        }

        /// <summary>
        /// Check if the prompt uses rows/columns without explicit grid keyword.
        /// Returns a clarification message if ambiguous, null otherwise.
        /// </summary>
        private string CheckGridClarification(string lower)
        {
            var rowMatch = Regex.Match(lower, @"(\d+)\s*rows?");
            if (!rowMatch.Success)
                rowMatch = Regex.Match(lower, @"rows?\s*(\d+)");

            var colMatch = Regex.Match(lower, @"(\d+)\s*columns?");
            if (!colMatch.Success)
                colMatch = Regex.Match(lower, @"columns?\s*(\d+)");

            if (!rowMatch.Success && !colMatch.Success)
                return null;

            var parts = new List<string>();
            if (rowMatch.Success)
            {
                int rowCount = int.Parse(rowMatch.Groups[1].Value);
                parts.Add($"{rowCount} horizontal row{(rowCount != 1 ? "s" : "")}");
            }
            if (colMatch.Success)
            {
                int colCount = int.Parse(colMatch.Groups[1].Value);
                parts.Add($"{colCount} vertical column{(colCount != 1 ? "s" : "")}");
            }

            string arrangement = string.Join(" and ", parts);
            return $"Did you mean Revit gridlines arranged as {arrangement}?\n\n" +
                   $"If so, please rephrase with 'gridlines' or 'grids'.\n" +
                   $"No changes were made to the model.";
        }

        /// <summary>
        /// Check if the prompt uses floors/stories without explicit level keyword.
        /// Returns a clarification message if ambiguous, null otherwise.
        /// </summary>
        private string CheckLevelClarification(string lower)
        {
            // Only trigger if it looks like a creation prompt
            string[] createKw = { "create", "add", "make", "build", "generate" };
            bool hasCreate = false;
            foreach (var kw in createKw)
            {
                if (lower.Contains(kw))
                    hasCreate = true;
            }
            if (!hasCreate)
                return null;

            // Don't trigger if "level" is present
            if (lower.Contains("level"))
                return null;

            var floorMatch = Regex.Match(lower, @"(\d+)\s*(?:floors?|stories|storeys?)");
            if (!floorMatch.Success)
                return null;

            int count = int.Parse(floorMatch.Groups[1].Value);
            return $"Did you mean Revit building levels \u2014 {count} levels?\n\n" +
                   $"If so, please rephrase with 'levels' " +
                   $"(e.g. 'Create {count} levels spaced 12 ft apart').\n" +
                   $"No changes were made to the model.";
        }

        /// <summary>
        /// Parse prompt text into JSON args for the identified capability.
        /// Mirrors the Python prompt_resolver logic.
        /// </summary>
        private string BuildInventoryArgsJson(string lower)
        {
            // Full scan is blocked at the dispatcher level (see block above).
            // This branch should never be reached, but defense-in-depth.
            bool isFull = lower.Contains("full inventory") ||
                          lower.Contains("run full inventorymodel") ||
                          lower.Contains("full scan") ||
                          lower.Contains("complete inventory") ||
                          lower.Contains("full values");
            bool isSampleValues = lower.Contains("sample values") ||
                                  lower.Contains("sample value");
            bool isSample = lower.Contains("sample") && !isSampleValues;
            bool isParameterSchema = lower.Contains("parameter schema") ||
                                      lower.Contains("param schema");
            bool isSchema = lower.Contains("schema") && !isParameterSchema;

            // Extract category filter: "inventory walls", "inventory for doors"
            string[] knownCategories = {
                "walls", "doors", "windows", "floors", "roofs", "ceilings",
                "columns", "beams", "stairs", "railings", "curtain panels",
                "curtain wall mullions", "furniture", "plumbing fixtures",
                "mechanical equipment", "electrical fixtures", "lighting fixtures",
                "generic models", "structural foundations", "structural framing",
                "duct systems", "ducts", "pipe systems", "pipes",
                "rooms", "areas", "levels", "views", "sheets"
            };
            string categoryFilter = null;
            foreach (var cat in knownCategories)
            {
                if (lower.Contains("inventory for " + cat) ||
                    lower.Contains("inventory " + cat) ||
                    lower.Contains("inventorymodel for " + cat) ||
                    lower.Contains("values for " + cat) ||
                    lower.Contains("schema for " + cat))
                {
                    categoryFilter = System.Globalization.CultureInfo
                        .CurrentCulture.TextInfo.ToTitleCase(cat);
                    break;
                }
            }

            // Extract level filter: "on level 1", "level 2", "for level ground"
            string levelFilter = null;
            var levelMatch = System.Text.RegularExpressions.Regex.Match(
                lower, @"(?:on |for |at )?level\s+(\S+(?:\s+\S+)?)");
            if (levelMatch.Success && !lower.Contains("level keyword") &&
                categoryFilter != "Levels")
            {
                string rawLevel = levelMatch.Groups[1].Value.Trim();
                // Avoid matching "levels" (the category) as a level filter
                if (rawLevel != "s" && rawLevel != "keyword")
                {
                    levelFilter = System.Globalization.CultureInfo
                        .CurrentCulture.TextInfo.ToTitleCase(rawLevel);
                }
            }

            // Extract batch size: "limit 10000", "max 5000", "batch 10000"
            int batchSize = 0;
            var batchMatch = System.Text.RegularExpressions.Regex.Match(
                lower, @"(?:max|limit|first|top|batch)\s+(\d+)");
            if (batchMatch.Success && !isSample)
            {
                batchSize = int.Parse(batchMatch.Groups[1].Value);
            }

            var args = new Dictionary<string, object>();

            if (isFull)
            {
                // Defense-in-depth: should be blocked before reaching here
                args["SummaryOnly"] = true;
                args["IncludeParameters"] = false;
                args["ScanMode"] = "summary";
            }
            else if (isSample)
            {
                args["SummaryOnly"] = false;
                args["MaxElements"] = 100;
                args["IncludeParameters"] = true;
                args["ScanMode"] = "sample";
            }
            else if (isParameterSchema && (categoryFilter != null || levelFilter != null))
            {
                // Constrained parameter schema: requires category or level
                args["SummaryOnly"] = false;
                args["ParameterSchemaOnly"] = true;
                args["IncludeParameters"] = false;
                args["ScanMode"] = "category_parameter_schema";
                if (categoryFilter != null)
                    args["CategoryFilter"] = new[] { categoryFilter };
                if (levelFilter != null)
                    args["LevelFilter"] = new[] { levelFilter };
            }
            else if (isParameterSchema)
            {
                // Whole-model parameter schema: BLOCKED — crashed Revit 2027.
                // Defense-in-depth: should be blocked before reaching here.
                args["SummaryOnly"] = true;
                args["IncludeParameters"] = false;
                args["ScanMode"] = "summary";
            }
            else if (isSchema && categoryFilter != null)
            {
                // Category object schema: element inventory for one category
                args["SummaryOnly"] = false;
                args["SchemaOnly"] = true;
                args["CategoryFilter"] = new[] { categoryFilter };
                args["IncludeParameters"] = false;
                args["ScanMode"] = "category_object_schema";
            }
            else if (isSampleValues && (categoryFilter != null || levelFilter != null))
            {
                // Constrained sample values: requires category/level/max.
                // Whole-model sample values crashed Revit 2027.
                args["SummaryOnly"] = false;
                args["SampleValues"] = true;
                args["SampleLimit"] = 5;
                args["MaxElements"] = batchSize > 0 ? batchSize : 25;
                args["IncludeParameters"] = true;
                args["ScanMode"] = "category_sample_values";
                if (categoryFilter != null)
                    args["CategoryFilter"] = new[] { categoryFilter };
                if (levelFilter != null)
                    args["LevelFilter"] = new[] { levelFilter };
            }
            else if (isSchema)
            {
                // Whole-model object schema: element/class/category inventory
                args["SummaryOnly"] = false;
                args["SchemaOnly"] = true;
                args["IncludeParameters"] = false;
                args["ScanMode"] = "object_schema";
            }
            else if (isSampleValues)
            {
                // Whole-model sample values: BLOCKED — crashed Revit 2027.
                // Defense-in-depth: should be blocked before reaching here.
                args["SummaryOnly"] = true;
                args["IncludeParameters"] = false;
                args["ScanMode"] = "summary";
            }
            else if (categoryFilter != null && levelFilter != null)
            {
                args["SummaryOnly"] = false;
                args["CategoryFilter"] = new[] { categoryFilter };
                args["LevelFilter"] = new[] { levelFilter };
                args["IncludeParameters"] = true;
                args["ScanMode"] = "category_level";
            }
            else if (categoryFilter != null)
            {
                args["SummaryOnly"] = false;
                args["CategoryFilter"] = new[] { categoryFilter };
                args["IncludeParameters"] = true;
                args["ScanMode"] = "category";
            }
            else if (levelFilter != null)
            {
                args["SummaryOnly"] = false;
                args["LevelFilter"] = new[] { levelFilter };
                args["IncludeParameters"] = true;
                args["ScanMode"] = "level";
            }
            else if (batchSize > 0)
            {
                // Whole-model batch defaults to object schema (safe).
                // Full value batching crashed Revit 2027 even at batch 100.
                args["SummaryOnly"] = false;
                args["SchemaOnly"] = true;
                args["IncludeParameters"] = false;
                args["BatchSize"] = batchSize;
                args["ScanMode"] = "object_schema";
            }
            else
            {
                // Default: safe summary scan
                args["SummaryOnly"] = true;
                args["IncludeParameters"] = false;
                args["ScanMode"] = "summary";
            }

            // Apply batch size to scoped modes (category/level/category_level)
            if (batchSize > 0 && !args.ContainsKey("BatchSize"))
            {
                args["BatchSize"] = batchSize;
            }

            return JsonConvert.SerializeObject(args);
        }

        private string BuildArgsJson(string lower, string capabilityName, string promptText)
        {
            if (capabilityName == "CreateLevels")
                return BuildLevelArgsJson(lower, promptText);

            if (capabilityName == "SetParameterValue")
                return BuildSetParameterValueArgsJson(lower, promptText);

            if (capabilityName != "CreateGrids")
                return "{}";

            int hCount = 5;
            int vCount = 5;
            double spacing = 30.0;
            double length = 0;

            bool hasVertical = false;
            bool hasHorizontal = false;

            // "10 vertical" or "10 columns" -> user wants vertical lines -> HorizontalCount
            var vertMatch = Regex.Match(lower, @"(\d+)\s*(?:vert(?:ical)?s?|columns?)");
            if (!vertMatch.Success)
                vertMatch = Regex.Match(lower, @"(?:vert(?:ical)?s?|columns?)\s*(\d+)");
            if (vertMatch.Success)
            {
                hCount = int.Parse(vertMatch.Groups[1].Value);
                hasVertical = true;
            }

            // "10 horizontal" or "10 rows" -> user wants horizontal lines -> VerticalCount
            var horizMatch = Regex.Match(lower, @"(\d+)\s*(?:horiz(?:ontal)?s?|rows?)");
            if (!horizMatch.Success)
                horizMatch = Regex.Match(lower, @"(?:horiz(?:ontal)?s?|rows?)\s*(\d+)");
            if (horizMatch.Success)
            {
                vCount = int.Parse(horizMatch.Groups[1].Value);
                hasHorizontal = true;
            }

            // "4 by 6 grid" or "4x6 grid"
            if (!hasVertical && !hasHorizontal)
            {
                var byMatch = Regex.Match(lower, @"(\d+)\s*(?:by|x)\s*(\d+)");
                if (byMatch.Success)
                {
                    hCount = int.Parse(byMatch.Groups[1].Value);
                    vCount = int.Parse(byMatch.Groups[2].Value);
                    hasVertical = true;
                    hasHorizontal = true;
                }
            }

            // Generic "10 grids"
            if (!hasVertical && !hasHorizontal)
            {
                var genericMatch = Regex.Match(lower,
                    @"(\d+)\s*(?:grid|grids|gridline|gridlines)");
                if (genericMatch.Success)
                {
                    int count = int.Parse(genericMatch.Groups[1].Value);
                    if (lower.Contains("vert") || lower.Contains("column"))
                    {
                        hCount = count;
                        hasVertical = true;
                    }
                    else if (lower.Contains("horiz") || lower.Contains("row"))
                    {
                        vCount = count;
                        hasHorizontal = true;
                    }
                    else
                    {
                        hCount = count;
                        vCount = count;
                        hasVertical = true;
                        hasHorizontal = true;
                    }
                }
            }

            // Variable spacing: "spacings 10, 5, 20, 10" or table format
            double[] horizSpacings = null;
            double[] vertSpacings = null;

            // Check for table-format spacing sections
            var vertTableSpacings = ParseTableSpacings(promptText, "vertical");
            var horizTableSpacings = ParseTableSpacings(promptText, "horizontal");

            if (vertTableSpacings != null)
            {
                horizSpacings = vertTableSpacings; // vertical grids → HorizontalSpacingsFeet
                if (!hasVertical)
                {
                    hCount = vertTableSpacings.Length + 1;
                    hasVertical = true;
                }
            }
            if (horizTableSpacings != null)
            {
                vertSpacings = horizTableSpacings; // horizontal grids → VerticalSpacingsFeet
                if (!hasHorizontal)
                {
                    vCount = horizTableSpacings.Length + 1;
                    hasHorizontal = true;
                }
            }

            // Comma-separated list: "spacings 10, 5, 20, 10"
            if (horizSpacings == null && vertSpacings == null)
            {
                var commaSpacings = ParseCommaSpacings(lower);
                if (commaSpacings != null)
                {
                    if (hasVertical && !hasHorizontal)
                    {
                        horizSpacings = commaSpacings;
                        hCount = commaSpacings.Length + 1;
                    }
                    else if (hasHorizontal && !hasVertical)
                    {
                        vertSpacings = commaSpacings;
                        vCount = commaSpacings.Length + 1;
                    }
                    else if (lower.Contains("vert") || lower.Contains("column"))
                    {
                        horizSpacings = commaSpacings;
                        hCount = commaSpacings.Length + 1;
                        hasVertical = true;
                    }
                    else if (lower.Contains("horiz") || lower.Contains("row"))
                    {
                        vertSpacings = commaSpacings;
                        vCount = commaSpacings.Length + 1;
                        hasHorizontal = true;
                    }
                }
            }

            // Inline comma spacings: "spaced 5, 6, and 20 feet apart"
            if (horizSpacings == null && vertSpacings == null)
            {
                var inlineSpacings = ParseInlineSpacings(lower);
                if (inlineSpacings != null)
                {
                    if (hasVertical && !hasHorizontal)
                    {
                        horizSpacings = inlineSpacings;
                        hCount = inlineSpacings.Length + 1;
                    }
                    else if (hasHorizontal && !hasVertical)
                    {
                        vertSpacings = inlineSpacings;
                        vCount = inlineSpacings.Length + 1;
                    }
                    else if (lower.Contains("vert") || lower.Contains("column"))
                    {
                        horizSpacings = inlineSpacings;
                        hCount = inlineSpacings.Length + 1;
                        hasVertical = true;
                    }
                    else if (lower.Contains("horiz") || lower.Contains("row"))
                    {
                        vertSpacings = inlineSpacings;
                        vCount = inlineSpacings.Length + 1;
                        hasHorizontal = true;
                    }
                }
            }

            // Single orientation: set other to 0 (re-evaluate after variable spacing)
            if (hasVertical && !hasHorizontal)
                vCount = 0;
            else if (hasHorizontal && !hasVertical)
                hCount = 0;

            // Uniform spacing
            var spacingMatch = Regex.Match(lower,
                @"(\d+\.?\d*)['\s]*(?:ft|feet|foot)?\s*(?:spacing|apart|between)");
            if (!spacingMatch.Success)
                spacingMatch = Regex.Match(lower,
                    @"spaced?\s+(?:evenly\s+)?(?:at\s+)?(\d+\.?\d*)['\s]*(?:ft|feet|foot)?");
            if (!spacingMatch.Success)
                spacingMatch = Regex.Match(lower,
                    @"spacing\s*(?:of\s+)?(\d+\.?\d*)['\s]*(?:ft|feet|foot)?");
            if (!spacingMatch.Success)
                spacingMatch = Regex.Match(lower,
                    @"every\s+(\d+\.?\d*)['\s]*(?:ft|feet|foot)?");
            if (spacingMatch.Success && horizSpacings == null && vertSpacings == null)
                spacing = double.Parse(spacingMatch.Groups[1].Value,
                    CultureInfo.InvariantCulture);

            // Length
            var lengthMatch = Regex.Match(lower,
                @"(\d+\.?\d*)['\s]*(?:ft|feet|foot)?\s*long");
            if (!lengthMatch.Success)
                lengthMatch = Regex.Match(lower,
                    @"length\s*(?:of\s*)?(\d+\.?\d*)['\s]*(?:ft|feet|foot)?");
            if (lengthMatch.Success)
                length = double.Parse(lengthMatch.Groups[1].Value,
                    CultureInfo.InvariantCulture);

            var obj = new Dictionary<string, object>
            {
                { "HorizontalCount", hCount },
                { "VerticalCount", vCount },
                { "SpacingFeet", spacing },
                { "Naming", "Default" },
                { "Length", length }
            };

            if (horizSpacings != null)
                obj["HorizontalSpacingsFeet"] = horizSpacings;
            if (vertSpacings != null)
                obj["VerticalSpacingsFeet"] = vertSpacings;

            return JsonConvert.SerializeObject(obj);
        }

        /// <summary>
        /// Parse comma-separated spacing values from prompt text.
        /// Matches patterns like "spacings 10, 5, 20, 10" or "with spacings 5, 6, and 20".
        /// </summary>
        private static double[] ParseCommaSpacings(string lower)
        {
            var match = Regex.Match(lower,
                @"spacings?\s+([\d]+\.?\d*(?:\s*[,]\s*(?:and\s+)?[\d]+\.?\d*)+)");
            if (!match.Success)
                return null;

            var raw = Regex.Replace(match.Groups[1].Value, @"\band\b", ",");
            var parts = raw.Split(',');
            var values = new List<double>();
            foreach (var part in parts)
            {
                var trimmed = part.Trim().TrimEnd('\'').Trim();
                trimmed = Regex.Replace(trimmed, @"\s*(ft|feet|foot)\s*$", "").Trim();
                if (string.IsNullOrEmpty(trimmed))
                    continue;
                double val;
                if (double.TryParse(trimmed, NumberStyles.Any,
                    CultureInfo.InvariantCulture, out val) && val > 0)
                {
                    values.Add(val);
                }
                else
                {
                    return null;
                }
            }
            return values.Count > 0 ? values.ToArray() : null;
        }

        /// <summary>
        /// Parse inline comma-separated spacing values without 'spacings' keyword.
        /// Matches: "spaced 5, 6, and 20 feet apart" or "spaced 5, 6 and 20 ft apart"
        /// </summary>
        private static double[] ParseInlineSpacings(string lower)
        {
            var match = Regex.Match(lower,
                @"spaced?\s+([\d]+\.?\d*\s*(?:[',]\s*(?:and\s+)?[\d]+\.?\d*)+)\s*['\ ]*(?:ft|feet|foot)?");
            if (!match.Success)
                return null;

            var raw = Regex.Replace(match.Groups[1].Value, @"\band\b", ",");
            var parts = raw.Split(',');
            var values = new List<double>();
            foreach (var part in parts)
            {
                var trimmed = part.Trim().TrimEnd('\'').Trim();
                trimmed = Regex.Replace(trimmed, @"\s*(ft|feet|foot)\s*$", "").Trim();
                if (string.IsNullOrEmpty(trimmed))
                    continue;
                double val;
                if (double.TryParse(trimmed, NumberStyles.Any,
                    CultureInfo.InvariantCulture, out val) && val > 0)
                {
                    values.Add(val);
                }
                else
                {
                    return null;
                }
            }
            return values.Count >= 2 ? values.ToArray() : null;
        }

        /// <summary>
        /// Check for arithmetic/progressive spacing sequences and variable
        /// spacing ambiguities.
        /// Returns a clarification message if the prompt is ambiguous, null otherwise.
        /// </summary>
        private string CheckGridSpacingClarification(string lower, string promptText)
        {
            // Detect arithmetic sequence phrases: "and so on", "etc", "..."
            string[] sequencePhrases = {
                @"and\s+so\s+on", @"etc\.?", @"and\s+so\s+forth",
                @"continuing", @"\.{3}"
            };
            bool hasSequencePhrase = false;
            foreach (var phrase in sequencePhrases)
            {
                if (Regex.IsMatch(lower, phrase))
                {
                    hasSequencePhrase = true;
                    break;
                }
            }
            if (hasSequencePhrase)
            {
                return "It looks like you want a progressive or arithmetic spacing sequence.\n\n" +
                       "Axiom currently supports uniform spacing or explicit per-bay spacing lists.\n" +
                       "Please provide the exact spacing values for each bay.";
            }

            // Detect variable spacing with ambiguous orientation or count mismatch
            bool hasOrientationKeyword = lower.Contains("vert") || lower.Contains("column")
                || lower.Contains("horiz") || lower.Contains("row");

            // Get variable spacings from comma or inline parsers
            var commaSpacings = ParseCommaSpacings(lower);
            var inlineSpacings = ParseInlineSpacings(lower);
            var spacings = commaSpacings ?? inlineSpacings;

            if (spacings == null)
                return null;

            // Get the count from the prompt
            int? requestedCount = null;
            var vertMatch = Regex.Match(lower, @"(\d+)\s*(?:vert(?:ical)?s?|columns?)");
            if (vertMatch.Success)
                requestedCount = int.Parse(vertMatch.Groups[1].Value);
            var horizMatch = Regex.Match(lower, @"(\d+)\s*(?:horiz(?:ontal)?s?|rows?)");
            if (!requestedCount.HasValue && horizMatch.Success)
                requestedCount = int.Parse(horizMatch.Groups[1].Value);
            if (!requestedCount.HasValue)
            {
                var genericMatch = Regex.Match(lower, @"(\d+)\s*(?:grid|grids|gridline|gridlines)");
                if (genericMatch.Success)
                    requestedCount = int.Parse(genericMatch.Groups[1].Value);
            }

            // Spacing count vs grid count mismatch
            if (requestedCount.HasValue && requestedCount.Value > 1)
            {
                int expectedIntervals = requestedCount.Value - 1;
                int actualIntervals = spacings.Length;
                if (actualIntervals != expectedIntervals)
                {
                    return $"You requested {requestedCount.Value} grids but provided " +
                           $"{actualIntervals} spacing value{(actualIntervals != 1 ? "s" : "")}.\n\n" +
                           $"{requestedCount.Value} grids require {expectedIntervals} spacing " +
                           $"interval{(expectedIntervals != 1 ? "s" : "")}.\n" +
                           $"No changes were made to the model.";
                }
            }

            // No orientation keyword with variable spacing
            if (!hasOrientationKeyword)
            {
                return "Variable spacing was specified but no grid orientation " +
                       "(vertical or horizontal) was given.\n\n" +
                       "Please specify the orientation (e.g. 'Create vertical grids " +
                       "with spacings ...').\n" +
                       "No changes were made to the model.";
            }

            return null;
        }

        /// <summary>
        /// Parse table-format spacing from prompt text.
        /// Matches lines like "1-2 = 10'" or "A-B = 15'" under Vertical:/Horizontal: sections.
        /// </summary>
        private static double[] ParseTableSpacings(string text, string section)
        {
            string lower = text.ToLowerInvariant();
            int sectionIdx = lower.IndexOf(section + ":");
            if (sectionIdx < 0)
                return null;

            string afterSection = text.Substring(sectionIdx + section.Length + 1);
            int nextSectionIdx = -1;
            string[] sectionHeaders = { "vertical:", "horizontal:" };
            foreach (var hdr in sectionHeaders)
            {
                if (hdr == section.ToLowerInvariant() + ":")
                    continue;
                int idx = afterSection.ToLowerInvariant().IndexOf(hdr);
                if (idx >= 0 && (nextSectionIdx < 0 || idx < nextSectionIdx))
                    nextSectionIdx = idx;
            }

            string sectionText = nextSectionIdx >= 0
                ? afterSection.Substring(0, nextSectionIdx)
                : afterSection;

            var tablePattern = new Regex(
                @"[\w]+-[\w]+\s*=\s*(\d+\.?\d*)\s*['\s]*(?:ft|feet|foot)?",
                RegexOptions.IgnoreCase);

            var matches = tablePattern.Matches(sectionText);
            if (matches.Count == 0)
                return null;

            var values = new List<double>();
            foreach (Match m in matches)
            {
                double val;
                if (double.TryParse(m.Groups[1].Value, NumberStyles.Any,
                    CultureInfo.InvariantCulture, out val) && val > 0)
                {
                    values.Add(val);
                }
                else
                {
                    return null;
                }
            }
            return values.Count > 0 ? values.ToArray() : null;
        }

        // ----- CreateLevels prompt parsing -----

        /// <summary>
        /// Build JSON args for CreateLevels from prompt text.
        /// Mirrors the Python _resolve_level_prompt logic.
        /// </summary>
        private string BuildLevelArgsJson(string lower, string promptText)
        {
            int count = 1;
            double ftf = 0;
            double startElev = 0;
            string[] levelNames = null;
            double[] varElevations = null;

            // Named level table: "Basement = -10'\n Ground = 0'"
            var namedTable = ParseNamedLevelTable(promptText);
            if (namedTable != null)
            {
                levelNames = namedTable.Item1;
                varElevations = namedTable.Item2;
                count = levelNames.Length;
            }
            else
            {
                // Variable elevations: "at 0, 12, 24" or "at elevations 0, 12, 24"
                var elevMatch = Regex.Match(lower,
                    @"(?:elevations?|at)\s+(-?\d+\.?\d*(?:\s*,\s*(?:and\s+)?-?\d+\.?\d*)+)");
                if (elevMatch.Success)
                {
                    string raw = Regex.Replace(elevMatch.Groups[1].Value, @"\band\b", "");
                    var parts = raw.Split(',');
                    var vals = new List<double>();
                    bool valid = true;
                    foreach (var p in parts)
                    {
                        var trimmed = p.Trim().TrimEnd('\'');
                        if (string.IsNullOrWhiteSpace(trimmed)) continue;
                        double v;
                        if (double.TryParse(trimmed, NumberStyles.Any,
                            CultureInfo.InvariantCulture, out v))
                        {
                            vals.Add(v);
                        }
                        else
                        {
                            valid = false;
                            break;
                        }
                    }
                    if (valid && vals.Count >= 2)
                    {
                        varElevations = vals.ToArray();
                        count = varElevations.Length;
                    }
                }
            }

            if (varElevations == null)
            {
                // Count: "5 levels" or "levels 5"
                var countMatch = Regex.Match(lower, @"(\d+)\s*levels?");
                if (!countMatch.Success)
                    countMatch = Regex.Match(lower, @"levels?\s+(\d+)");
                if (countMatch.Success)
                    count = int.Parse(countMatch.Groups[1].Value);

                // Floor-to-floor spacing
                var ftfMatch = Regex.Match(lower,
                    @"(\d+\.?\d*)['\s]*(?:ft|feet|foot)?\s*(?:apart|spacing|spaced)");
                if (!ftfMatch.Success)
                    ftfMatch = Regex.Match(lower,
                        @"spaced?\s+(?:at\s+)?(\d+\.?\d*)['\s]*(?:ft|feet|foot)?");
                if (!ftfMatch.Success)
                    ftfMatch = Regex.Match(lower,
                        @"(?:floor[\s-]*to[\s-]*floor|ftf)\s+(?:of\s+)?(\d+\.?\d*)['\s]*(?:ft|feet|foot)?");
                if (ftfMatch.Success)
                    ftf = double.Parse(ftfMatch.Groups[1].Value,
                        CultureInfo.InvariantCulture);

                // Start elevation
                var startMatch = Regex.Match(lower,
                    @"start(?:ing)?\s+(?:at|from)\s+(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?");
                if (!startMatch.Success)
                    startMatch = Regex.Match(lower,
                        @"(?:from|at)\s+elevation\s+(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?");
                if (startMatch.Success)
                    startElev = double.Parse(startMatch.Groups[1].Value,
                        CultureInfo.InvariantCulture);

                // Named levels: "named Level 1, Level 2, Level 3"
                var namesMatch = Regex.Match(lower,
                    @"named\s+(.+?)(?:\s+(?:spaced|at|starting|from)\b|$)");
                if (namesMatch.Success)
                {
                    var parts = namesMatch.Groups[1].Value.Split(',');
                    var names = new List<string>();
                    foreach (var p in parts)
                    {
                        var trimmed = p.Trim();
                        if (!string.IsNullOrWhiteSpace(trimmed))
                            names.Add(trimmed);
                    }
                    if (names.Count > 0)
                        levelNames = names.ToArray();
                }
            }

            var obj = new Dictionary<string, object>
            {
                { "LevelCount", count },
                { "FloorToFloorFeet", ftf },
                { "StartElevationFeet", startElev }
            };

            if (levelNames != null)
                obj["LevelNames"] = levelNames;
            if (varElevations != null)
                obj["VariableElevationsFeet"] = varElevations;

            return JsonConvert.SerializeObject(obj);
        }

        /// <summary>
        /// Parse named level table format from prompt text.
        /// Matches lines like "Basement = -10'" or "Ground = 0'".
        /// Returns (names[], elevations[]) or null.
        /// </summary>
        private static Tuple<string[], double[]> ParseNamedLevelTable(string text)
        {
            var pattern = new Regex(
                @"^\s*([A-Za-z][A-Za-z0-9 ]*?)\s*=\s*(-?\d+\.?\d*)\s*['\s]*(?:ft|feet|foot)?\s*$",
                RegexOptions.Multiline);

            var matches = pattern.Matches(text);
            if (matches.Count < 2)
                return null;

            var names = new List<string>();
            var elevations = new List<double>();
            foreach (Match m in matches)
            {
                names.Add(m.Groups[1].Value.Trim());
                double val;
                if (double.TryParse(m.Groups[2].Value, NumberStyles.Any,
                    CultureInfo.InvariantCulture, out val))
                {
                    elevations.Add(val);
                }
                else
                {
                    return null;
                }
            }

            return Tuple.Create(names.ToArray(), elevations.ToArray());
        }

        // Word-to-number mapping for small counts
        private static readonly Dictionary<string, int> WordNumbers
            = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            { "one", 1 }, { "two", 2 }, { "three", 3 }, { "four", 4 }, { "five", 5 },
            { "six", 6 }, { "seven", 7 }, { "eight", 8 }, { "nine", 9 }, { "ten", 10 },
        };

        /// <summary>
        /// Parse a SetParameterValue prompt and build the args JSON.
        /// Supports: [Apply] Set Parameter to Value for N Category
        /// Both quoted and unquoted values.
        /// </summary>
        private string BuildSetParameterValueArgsJson(string lower, string promptText)
        {
            string text = promptText.Trim();
            string mode = "preview";

            // Detect apply mode
            if (Regex.IsMatch(text, @"(?i)^apply\b"))
            {
                mode = "apply";
                text = Regex.Replace(text, @"(?i)^apply\s+", "");
            }

            // Strip leading "set"
            text = Regex.Replace(text, @"(?i)^set\s+", "");

            // Find trailing "for <N> <Category>"
            var trailing = Regex.Match(text, @"\bfor\s+(\w+)\s+(.+)$", RegexOptions.IgnoreCase);
            if (!trailing.Success)
                return "{}";

            string countStr = trailing.Groups[1].Value;
            string category = trailing.Groups[2].Value.Trim();

            // Everything before "for ..." is "<Parameter> to <Value>"
            string beforeFor = text.Substring(0, trailing.Index).Trim();

            // Split at " to " to get parameter and value
            var toMatch = Regex.Match(beforeFor, @"\bto\s+", RegexOptions.IgnoreCase);
            if (!toMatch.Success)
                return "{}";

            string parameterName = beforeFor.Substring(0, toMatch.Index).Trim();
            string rawValue = beforeFor.Substring(toMatch.Index + toMatch.Length).Trim();

            // Strip surrounding quotes if present
            if (rawValue.Length >= 2 && rawValue[0] == '"' && rawValue[rawValue.Length - 1] == '"')
                rawValue = rawValue.Substring(1, rawValue.Length - 2);

            // Parse count
            int count;
            if (!int.TryParse(countStr, out count))
            {
                if (!WordNumbers.TryGetValue(countStr, out count))
                    count = 1;
            }

            var args = new Models.SetParameterValueParameters
            {
                Category = category,
                ParameterName = parameterName,
                Value = rawValue,
                ElementCount = count,
                Mode = mode,
                ActiveViewOnly = true,
                RawPrompt = promptText
            };

            return JsonConvert.SerializeObject(args);
        }
    }

    /// <summary>
    /// Result of dispatching a prompt to a capability.
    /// </summary>
    public class PromptDispatchResult
    {
        public bool Success { get; set; }
        public bool NeedsClarification { get; set; }
        public string CapabilityName { get; set; }
        public string Message { get; set; }
        public CapabilityResult CapabilityResult { get; set; }

        public static PromptDispatchResult Fail(string message)
        {
            return new PromptDispatchResult
            {
                Success = false,
                Message = message
            };
        }

        public static PromptDispatchResult Clarification(string message)
        {
            return new PromptDispatchResult
            {
                Success = false,
                NeedsClarification = true,
                Message = message
            };
        }
    }
}

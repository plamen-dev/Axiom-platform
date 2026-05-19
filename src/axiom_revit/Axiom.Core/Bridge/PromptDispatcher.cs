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
                    "  - Model inventory (e.g. \"Run InventoryModel\")\n\n" +
                    "Unsupported prompts will be available in future updates.");
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
                    "  - Model inventory (e.g. \"Run InventoryModel\")\n\n" +
                    "Unsupported prompts will be available in future updates.");
            }

            IAxiomCapability capability;
            if (!_registry.TryGet(capabilityName, out capability))
            {
                return PromptDispatchResult.Fail(
                    $"Capability not registered: {capabilityName}\n\n" +
                    "The capability was recognized but is not available in this build.");
            }

            // Build args JSON from the prompt (pass original text for table parsing)
            string argsJson = capabilityName == "InventoryModel"
                ? "{}" : BuildArgsJson(lower, capabilityName, promptText);

            try
            {
                var result = capability.Execute(doc, argsJson, false);
                return new PromptDispatchResult
                {
                    Success = result.Status == "SUCCESS",
                    CapabilityName = capabilityName,
                    CapabilityResult = result,
                    Message = result.Status == "SUCCESS"
                        ? $"Capability: {capabilityName}\n" +
                          $"Status: SUCCESS\n" +
                          $"Created: {result.CreatedIds.Count} element(s)\n" +
                          $"Duration: {result.DurationMs}ms"
                        : $"Capability: {capabilityName}\n" +
                          $"Status: FAILED\n" +
                          $"Errors: {string.Join("; ", result.Errors)}"
                };
            }
            catch (Exception ex)
            {
                return PromptDispatchResult.Fail(
                    $"Capability: {capabilityName}\n" +
                    $"Execution failed: {ex.Message}");
            }
        }

        private string ResolveCapability(string lower)
        {
            // Inventory keywords (checked first — read-only, unambiguous)
            string[] inventoryKeywords = {
                "run inventorymodel", "inventory model", "inventorymodel",
                "list all model elements", "scan model parameters",
                "extract model parameters", "model inventory"
            };
            foreach (var kw in inventoryKeywords)
            {
                if (lower.Contains(kw))
                    return "InventoryModel";
            }

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
        private string BuildArgsJson(string lower, string capabilityName, string promptText)
        {
            if (capabilityName == "CreateLevels")
                return BuildLevelArgsJson(lower, promptText);

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
        /// Matches patterns like "spacings 10, 5, 20, 10" or "with spacings 10,5,20".
        /// </summary>
        private static double[] ParseCommaSpacings(string lower)
        {
            var match = Regex.Match(lower,
                @"spacings?\s+([\d]+\.?\d*(?:\s*,\s*[\d]+\.?\d*)+)");
            if (!match.Success)
                return null;

            var parts = match.Groups[1].Value.Split(',');
            var values = new List<double>();
            foreach (var part in parts)
            {
                var trimmed = part.Trim().TrimEnd('\'');
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

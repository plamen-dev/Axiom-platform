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
    /// Capability wrapper for grid creation.
    /// Delegates to the existing GridCreationService — does NOT rewrite grid logic.
    ///
    /// Lives in Axiom.RevitAddin because it depends on GridCreationService.
    /// Implements IAxiomCapability from Axiom.Core (shared contract).
    /// </summary>
    public class GridCapability : IAxiomCapability
    {
        private const double DefaultTailFeet = 10.0;

        public string Name => "CreateGrids";

        public string Description =>
            "Creates a grid system with horizontal (numeric) and vertical (alphabetic) grids.";

        public Type ParameterType => typeof(GridParameters);

        public CapabilityResult Execute(Document doc, string argsJson, bool simulate)
        {
            var sw = Stopwatch.StartNew();
            var result = new CapabilityResult();

            GridParameters parameters;
            try
            {
                parameters = JsonConvert.DeserializeObject<GridParameters>(argsJson);
            }
            catch (Exception ex)
            {
                result.Status = "FAILED";
                result.Errors.Add($"Invalid parameters JSON: {ex.Message}");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // --- Validation (ported from GridsCommand) ---

            if (parameters.HorizontalCount < 0 || parameters.VerticalCount < 0)
            {
                result.Status = "FAILED";
                result.Errors.Add("Grid counts must not be negative.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            if (parameters.HorizontalCount == 0 && parameters.VerticalCount == 0)
            {
                result.Status = "FAILED";
                result.Errors.Add("At least one grid count must be greater than zero.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // Variable spacing validation
            bool hasHorizSpacings = parameters.HorizontalSpacingsFeet != null
                && parameters.HorizontalSpacingsFeet.Length > 0;
            bool hasVertSpacings = parameters.VerticalSpacingsFeet != null
                && parameters.VerticalSpacingsFeet.Length > 0;

            if (hasHorizSpacings)
            {
                if (parameters.HorizontalSpacingsFeet.Length != parameters.HorizontalCount - 1)
                {
                    result.Status = "FAILED";
                    result.Errors.Add(
                        $"HorizontalSpacingsFeet has {parameters.HorizontalSpacingsFeet.Length} " +
                        $"values but HorizontalCount is {parameters.HorizontalCount} " +
                        $"(expected {parameters.HorizontalCount - 1} spacings).");
                    result.DurationMs = sw.ElapsedMilliseconds;
                    return result;
                }
                if (parameters.HorizontalSpacingsFeet.Any(s => s <= 0))
                {
                    result.Status = "FAILED";
                    result.Errors.Add("All HorizontalSpacingsFeet values must be positive.");
                    result.DurationMs = sw.ElapsedMilliseconds;
                    return result;
                }
            }

            if (hasVertSpacings)
            {
                if (parameters.VerticalSpacingsFeet.Length != parameters.VerticalCount - 1)
                {
                    result.Status = "FAILED";
                    result.Errors.Add(
                        $"VerticalSpacingsFeet has {parameters.VerticalSpacingsFeet.Length} " +
                        $"values but VerticalCount is {parameters.VerticalCount} " +
                        $"(expected {parameters.VerticalCount - 1} spacings).");
                    result.DurationMs = sw.ElapsedMilliseconds;
                    return result;
                }
                if (parameters.VerticalSpacingsFeet.Any(s => s <= 0))
                {
                    result.Status = "FAILED";
                    result.Errors.Add("All VerticalSpacingsFeet values must be positive.");
                    result.DurationMs = sw.ElapsedMilliseconds;
                    return result;
                }
            }

            // Uniform spacing required when no variable spacing is provided
            if (!hasHorizSpacings && !hasVertSpacings && parameters.SpacingFeet <= 0)
            {
                result.Status = "FAILED";
                result.Errors.Add("Grid spacing must be greater than zero.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // For mixed mode (one variable, one uniform), uniform spacing still needed
            if (!hasHorizSpacings && parameters.HorizontalCount > 1 && parameters.SpacingFeet <= 0)
            {
                result.Status = "FAILED";
                result.Errors.Add("SpacingFeet must be positive for uniform vertical grid spacing.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }
            if (!hasVertSpacings && parameters.VerticalCount > 1 && parameters.SpacingFeet <= 0)
            {
                result.Status = "FAILED";
                result.Errors.Add("SpacingFeet must be positive for uniform horizontal grid spacing.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            double derivedHorizontalSpan = hasHorizSpacings
                ? parameters.HorizontalSpacingsFeet.Sum()
                : (parameters.HorizontalCount > 1
                    ? (parameters.HorizontalCount - 1) * parameters.SpacingFeet : 0);
            double derivedVerticalSpan = hasVertSpacings
                ? parameters.VerticalSpacingsFeet.Sum()
                : (parameters.VerticalCount > 1
                    ? (parameters.VerticalCount - 1) * parameters.SpacingFeet : 0);

            if (DefaultTailFeet <= 0 || derivedHorizontalSpan < 0 || derivedVerticalSpan < 0)
            {
                result.Status = "FAILED";
                result.Errors.Add("Derived grid extents are invalid.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // Check for duplicate grid names in the model
            var expectedNumericNames = Enumerable.Range(1, parameters.HorizontalCount)
                .Select(i => i.ToString()).ToList();
            var expectedAlphaNames = Enumerable.Range(0, parameters.VerticalCount)
                .Select(i => GetAlphabeticName(i)).ToList();

            HashSet<string> existingNames = new FilteredElementCollector(doc)
                .OfClass(typeof(Grid))
                .Cast<Grid>()
                .Select(g => g.Name)
                .ToHashSet(StringComparer.OrdinalIgnoreCase);

            var conflicts = expectedNumericNames
                .Concat(expectedAlphaNames)
                .Where(n => existingNames.Contains(n))
                .ToList();

            if (conflicts.Any())
            {
                result.Status = "FAILED";
                result.Errors.Add(
                    $"Grid name conflicts: {string.Join(", ", conflicts)}");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // --- Simulation mode: validate only ---
            if (simulate)
            {
                result.Status = "SUCCESS";
                result.OutputData["simulated"] = true;
                result.OutputData["grid_count"] =
                    parameters.HorizontalCount + parameters.VerticalCount;
                result.OutputData["span_x_feet"] = derivedHorizontalSpan;
                result.OutputData["span_y_feet"] = derivedVerticalSpan;
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // --- Execution: delegate to existing service ---
            var service = new GridCreationService();
            service.CreateHorizontalGrids(doc, parameters);

            int totalGrids = parameters.HorizontalCount + parameters.VerticalCount;
            for (int i = 1; i <= parameters.HorizontalCount; i++)
                result.CreatedIds.Add($"grid_{i}");
            for (int i = 0; i < parameters.VerticalCount; i++)
                result.CreatedIds.Add($"grid_{GetAlphabeticName(i)}");

            result.Status = "SUCCESS";
            result.OutputData["grid_count"] = totalGrids;
            result.OutputData["span_x_feet"] = derivedHorizontalSpan;
            result.OutputData["span_y_feet"] = derivedVerticalSpan;
            result.DurationMs = sw.ElapsedMilliseconds;
            return result;
        }

        private static string GetAlphabeticName(int index)
        {
            string name = string.Empty;
            index++;
            while (index > 0)
            {
                int r = (index - 1) % 26;
                name = (char)('A' + r) + name;
                index = (index - 1) / 26;
            }
            return name;
        }
    }
}

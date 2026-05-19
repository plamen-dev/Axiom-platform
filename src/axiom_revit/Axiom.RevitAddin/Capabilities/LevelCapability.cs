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
    /// Capability wrapper for level creation.
    /// Validates parameters and delegates to LevelCreationService.
    /// Follows the same pattern as GridCapability.
    /// </summary>
    public class LevelCapability : IAxiomCapability
    {
        public string Name => "CreateLevels";

        public string Description =>
            "Creates building levels at specified elevations.";

        public Type ParameterType => typeof(LevelParameters);

        public CapabilityResult Execute(Document doc, string argsJson, bool simulate)
        {
            var sw = Stopwatch.StartNew();
            var result = new CapabilityResult();

            LevelParameters parameters;
            try
            {
                parameters = JsonConvert.DeserializeObject<LevelParameters>(argsJson);
            }
            catch (Exception ex)
            {
                result.Status = "FAILED";
                result.Errors.Add($"Invalid parameters JSON: {ex.Message}");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // --- Validation ---

            if (parameters.LevelCount <= 0)
            {
                result.Status = "FAILED";
                result.Errors.Add("LevelCount must be greater than 0.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            bool hasVarElevations = parameters.VariableElevationsFeet != null
                && parameters.VariableElevationsFeet.Length > 0;

            // FloorToFloorFeet required when no variable elevations and count > 1
            if (!hasVarElevations && parameters.LevelCount > 1
                && parameters.FloorToFloorFeet <= 0)
            {
                result.Status = "FAILED";
                result.Errors.Add(
                    "FloorToFloorFeet must be provided and > 0 when creating " +
                    "multiple levels without variable elevations.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // Variable elevations length must match count
            if (hasVarElevations &&
                parameters.VariableElevationsFeet.Length != parameters.LevelCount)
            {
                result.Status = "FAILED";
                result.Errors.Add(
                    $"VariableElevationsFeet has {parameters.VariableElevationsFeet.Length} " +
                    $"values but LevelCount is {parameters.LevelCount}.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // Level names length must match count
            bool hasNames = parameters.LevelNames != null
                && parameters.LevelNames.Length > 0;
            if (hasNames && parameters.LevelNames.Length != parameters.LevelCount)
            {
                result.Status = "FAILED";
                result.Errors.Add(
                    $"LevelNames has {parameters.LevelNames.Length} names " +
                    $"but LevelCount is {parameters.LevelCount}.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // Compute elevations
            double[] elevations;
            if (hasVarElevations)
            {
                elevations = parameters.VariableElevationsFeet;
            }
            else
            {
                elevations = new double[parameters.LevelCount];
                for (int i = 0; i < parameters.LevelCount; i++)
                {
                    elevations[i] = parameters.StartElevationFeet
                        + i * parameters.FloorToFloorFeet;
                }
            }

            // Check for duplicate elevations
            var uniqueElevations = new HashSet<double>(elevations);
            if (uniqueElevations.Count != elevations.Length)
            {
                result.Status = "FAILED";
                result.Errors.Add("Duplicate elevation detected. Each level must have a unique elevation.");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // Check for duplicate names
            if (hasNames)
            {
                var uniqueNames = new HashSet<string>(
                    parameters.LevelNames, StringComparer.OrdinalIgnoreCase);
                if (uniqueNames.Count != parameters.LevelNames.Length)
                {
                    result.Status = "FAILED";
                    result.Errors.Add("Duplicate level name detected.");
                    result.DurationMs = sw.ElapsedMilliseconds;
                    return result;
                }
            }

            // Check for existing level name conflicts in the model
            var expectedNames = hasNames
                ? parameters.LevelNames.ToList()
                : Enumerable.Range(1, parameters.LevelCount)
                    .Select(i => $"Level {i}").ToList();

            HashSet<string> existingNames = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .Select(l => l.Name)
                .ToHashSet(StringComparer.OrdinalIgnoreCase);

            var conflicts = expectedNames
                .Where(n => existingNames.Contains(n))
                .ToList();

            if (conflicts.Any())
            {
                result.Warnings.Add(
                    $"Level name conflicts with existing: {string.Join(", ", conflicts)}. " +
                    "Revit may auto-rename these levels.");
            }

            // --- Simulation mode: validate only ---
            if (simulate)
            {
                result.Status = "SUCCESS";
                result.OutputData["simulated"] = true;
                result.OutputData["level_count"] = parameters.LevelCount;
                result.OutputData["elevations_feet"] = elevations;
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // --- Execution: delegate to service ---
            var service = new LevelCreationService();
            service.CreateLevels(doc, parameters, elevations);

            for (int i = 0; i < parameters.LevelCount; i++)
            {
                string name = hasNames ? parameters.LevelNames[i] : $"Level {i + 1}";
                result.CreatedIds.Add($"level_{name}");
            }

            result.Status = "SUCCESS";
            result.OutputData["level_count"] = parameters.LevelCount;
            result.OutputData["elevations_feet"] = elevations;
            result.DurationMs = sw.ElapsedMilliseconds;
            return result;
        }
    }
}

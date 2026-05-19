using System;
using System.Collections.Generic;
using System.Diagnostics;
using Autodesk.Revit.DB;
using Axiom.Core.Capabilities;
using Axiom.Core.Models;
using Axiom.RevitAddin.Services;
using Newtonsoft.Json;

namespace Axiom.RevitAddin.Capabilities
{
    /// <summary>
    /// Read-only capability that inventories all elements and parameters
    /// from the active Revit model. No model modifications.
    /// </summary>
    public class InventoryModelCapability : IAxiomCapability
    {
        public string Name => "InventoryModel";

        public string Description =>
            "Scans the active model and returns a structured inventory of " +
            "all elements and their parameters. Read-only — no model changes.";

        public Type ParameterType => typeof(InventoryParameters);

        public CapabilityResult Execute(Document doc, string argsJson, bool simulate)
        {
            var sw = Stopwatch.StartNew();
            var result = new CapabilityResult();

            InventoryParameters parameters;
            try
            {
                parameters = string.IsNullOrWhiteSpace(argsJson)
                    ? new InventoryParameters()
                    : JsonConvert.DeserializeObject<InventoryParameters>(argsJson)
                      ?? new InventoryParameters();
            }
            catch (Exception ex)
            {
                result.Status = "FAILED";
                result.Errors.Add($"Invalid parameters JSON: {ex.Message}");
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // Simulation mode: return mock inventory structure
            if (simulate)
            {
                result.Status = "SUCCESS";
                result.OutputData["simulated"] = true;
                result.OutputData["element_count"] = 0;
                result.OutputData["type_count"] = 0;
                result.OutputData["parameter_count"] = 0;
                result.OutputData["elements"] = new List<object>();
                result.DurationMs = sw.ElapsedMilliseconds;
                return result;
            }

            // Real execution: collect inventory
            try
            {
                var service = new ModelInventoryService();
                var inventory = service.CollectInventory(doc, parameters);

                int instanceCount = 0;
                int typeCount = 0;
                int paramCount = 0;
                var serializedElements = new List<Dictionary<string, object>>();

                foreach (var elem in inventory.Elements)
                {
                    if (elem.IsType) typeCount++;
                    else instanceCount++;

                    paramCount += elem.Parameters.Count;

                    var elemDict = new Dictionary<string, object>
                    {
                        { "ElementId", elem.ElementId },
                        { "UniqueId", elem.UniqueId },
                        { "Category", elem.Category },
                        { "ClassName", elem.ClassName },
                        { "Name", elem.Name },
                        { "FamilyName", elem.FamilyName ?? "" },
                        { "TypeName", elem.TypeName ?? "" },
                        { "LevelName", elem.LevelName ?? "" },
                        { "WorksetName", elem.WorksetName ?? "" },
                        { "IsType", elem.IsType },
                    };

                    var paramList = new List<Dictionary<string, object>>();
                    foreach (var p in elem.Parameters)
                    {
                        paramList.Add(new Dictionary<string, object>
                        {
                            { "Name", p.Name },
                            { "StorageType", p.StorageType },
                            { "ValueString", p.ValueString ?? "" },
                            { "ValueDouble", p.ValueDouble },
                            { "ValueInt", p.ValueInt },
                            { "BuiltInParameterId", p.BuiltInParameterId ?? "" },
                            { "IsReadOnly", p.IsReadOnly },
                        });
                    }
                    elemDict["Parameters"] = paramList;
                    serializedElements.Add(elemDict);
                }

                result.Status = "SUCCESS";
                result.OutputData["element_count"] = instanceCount;
                result.OutputData["type_count"] = typeCount;
                result.OutputData["parameter_count"] = paramCount;
                result.OutputData["elements"] = serializedElements;
                result.DurationMs = sw.ElapsedMilliseconds;
            }
            catch (Exception ex)
            {
                result.Status = "FAILED";
                result.Errors.Add($"Inventory collection failed: {ex.Message}");
                result.DurationMs = sw.ElapsedMilliseconds;
            }

            return result;
        }
    }
}

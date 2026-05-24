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

            // Real execution: route based on scan mode
            try
            {
                var service = new ModelInventoryService();

                if (parameters.ParameterSchemaOnly)
                {
                    // Parameter schema: collect parameter definitions via CollectSchema()
                    var schema = service.CollectSchema(doc, parameters);

                    var serializedParams = new List<Dictionary<string, object>>();
                    foreach (var p in schema.Parameters)
                    {
                        serializedParams.Add(new Dictionary<string, object>
                        {
                            { "ParameterName", p.ParameterName },
                            { "StorageType", p.StorageType },
                            { "BuiltInParameterId", p.BuiltInParameterId ?? "" },
                            { "IsReadOnly", p.IsReadOnly },
                            { "IsInstanceParam", p.IsInstanceParam },
                            { "IsTypeParam", p.IsTypeParam },
                            { "ObservedCount", p.ObservedCount },
                            { "ObservedOnCategories", p.ObservedOnCategories },
                            { "ObservedOnClasses", p.ObservedOnClasses },
                            { "DataTypeId", p.DataTypeId ?? "" },
                            { "DataTypeLabel", p.DataTypeLabel ?? "" },
                            { "GroupTypeId", p.GroupTypeId ?? "" },
                            { "GroupTypeLabel", p.GroupTypeLabel ?? "" },
                            { "IsMeasurableSpec", p.IsMeasurableSpec },
                            { "UnitTypeId", p.UnitTypeId ?? "" },
                            { "UnitLabel", p.UnitLabel ?? "" },
                            { "DisciplineLabel", p.DisciplineLabel ?? "" },
                        });
                    }

                    result.Status = "SUCCESS";
                    result.OutputData["scan_mode"] = parameters.ScanMode;
                    result.OutputData["instance_count"] = schema.InstanceCount;
                    result.OutputData["type_count"] = schema.TypeCount;
                    result.OutputData["element_count"] = schema.InstanceCount + schema.TypeCount;
                    result.OutputData["parameter_definition_count"] = schema.Parameters.Count;
                    result.OutputData["error_count"] = schema.ErrorCount;
                    result.OutputData["category_counts"] = schema.CategoryCounts;
                    result.OutputData["parameter_definitions"] = serializedParams;
                    if (parameters.CategoryFilter != null && parameters.CategoryFilter.Length > 0)
                        result.OutputData["object_category"] = string.Join(", ", parameters.CategoryFilter);
                    result.DurationMs = sw.ElapsedMilliseconds;
                }
                else
                {
                    // Object schema / summary / category / sample / batched modes
                    var inventory = service.CollectInventory(doc, parameters);

                    int instanceCount = inventory.InstanceCount;
                    int typeCount = inventory.TypeCount;
                    int paramCount = 0;

                    var serializedElements = new List<Dictionary<string, object>>();
                    if (!parameters.SummaryOnly)
                    {
                        foreach (var elem in inventory.Elements)
                        {
                            try
                            {
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
                            catch (Exception)
                            {
                                // Skip individual element serialization errors
                            }
                        }
                    }

                    result.Status = "SUCCESS";
                    result.OutputData["scan_mode"] = parameters.ScanMode;
                    result.OutputData["instance_count"] = instanceCount;
                    result.OutputData["type_count"] = typeCount;
                    result.OutputData["element_count"] = instanceCount + typeCount;
                    result.OutputData["parameter_count"] = paramCount;
                    result.OutputData["error_count"] = inventory.ErrorCount;
                    result.OutputData["category_counts"] = inventory.CategoryCounts;
                    result.OutputData["elements"] = serializedElements;
                    if (parameters.CategoryFilter != null && parameters.CategoryFilter.Length > 0)
                        result.OutputData["object_category"] = string.Join(", ", parameters.CategoryFilter);
                    result.DurationMs = sw.ElapsedMilliseconds;
                }
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

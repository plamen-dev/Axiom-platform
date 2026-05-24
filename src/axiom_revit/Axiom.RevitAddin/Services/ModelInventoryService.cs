using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Axiom.Core.Compat;
using Axiom.Core.Models;

namespace Axiom.RevitAddin.Services
{
    /// <summary>
    /// Read-only service that inventories elements and parameters from
    /// the active Revit model. No transactions, no model modifications.
    /// Supports summary-only, category-filtered, level-filtered, sample,
    /// chunked scan modes, and batched/paginated extraction.
    /// </summary>
    public class ModelInventoryService
    {
        /// <summary>
        /// Scan the model and return structured element/parameter data.
        /// Respects SummaryOnly, MaxElements, CategoryFilter, LevelFilter,
        /// and per-element exception handling for crash safety.
        /// </summary>
        public InventoryOutput CollectInventory(
            Document doc, InventoryParameters parameters)
        {
            parameters.ApplyDefaults();

            var output = new InventoryOutput();
            var categoryFilter = parameters.CategoryFilter != null
                ? new HashSet<string>(parameters.CategoryFilter,
                    StringComparer.OrdinalIgnoreCase)
                : null;
            var levelFilter = parameters.LevelFilter != null
                ? new HashSet<string>(parameters.LevelFilter,
                    StringComparer.OrdinalIgnoreCase)
                : null;

            int maxElements = parameters.MaxElements > 0
                ? parameters.MaxElements : int.MaxValue;
            int processed = 0;

            // Collect all elements (instances)
            var collector = new FilteredElementCollector(doc)
                .WhereElementIsNotElementType();

            foreach (Element elem in collector)
            {
                if (processed >= maxElements) break;
                if (elem == null) continue;

                try
                {
                    string catName = elem.Category?.Name ?? "(No Category)";

                    if (categoryFilter != null && !categoryFilter.Contains(catName))
                        continue;

                    // Level filter: skip elements not on requested level(s)
                    if (levelFilter != null)
                    {
                        string elemLevel = GetElementLevelName(elem);
                        if (string.IsNullOrEmpty(elemLevel) || !levelFilter.Contains(elemLevel))
                            continue;
                    }

                    // Track category counts (always, even in summary mode)
                    if (!output.CategoryCounts.ContainsKey(catName))
                        output.CategoryCounts[catName] = 0;
                    output.CategoryCounts[catName]++;
                    output.InstanceCount++;

                    if (!parameters.SummaryOnly)
                    {
                        var entry = BuildElementEntry(elem, isType: false);
                        if (parameters.IncludeInstanceParameters)
                            entry.Parameters = CollectParameters(elem);
                        output.Elements.Add(entry);
                    }

                    processed++;
                }
                catch (Exception)
                {
                    output.ErrorCount++;
                }
            }

            // Collect element types
            var typeCollector = new FilteredElementCollector(doc)
                .WhereElementIsElementType();

            foreach (Element typeElem in typeCollector)
            {
                if (processed >= maxElements) break;
                if (typeElem == null) continue;

                try
                {
                    string catName = typeElem.Category?.Name ?? "(No Category)";

                    if (categoryFilter != null && !categoryFilter.Contains(catName))
                        continue;

                    // Track category counts for types
                    string typeCatKey = catName + " (Types)";
                    if (!output.CategoryCounts.ContainsKey(typeCatKey))
                        output.CategoryCounts[typeCatKey] = 0;
                    output.CategoryCounts[typeCatKey]++;
                    output.TypeCount++;

                    if (!parameters.SummaryOnly)
                    {
                        var entry = BuildElementEntry(typeElem, isType: true);
                        if (parameters.IncludeTypeParameters)
                            entry.Parameters = CollectParameters(typeElem);
                        output.Elements.Add(entry);
                    }

                    processed++;
                }
                catch (Exception)
                {
                    output.ErrorCount++;
                }
            }

            return output;
        }

        private ElementEntry BuildElementEntry(Element elem, bool isType)
        {
            var entry = new ElementEntry
            {
                ElementId = RevitElementIdCompat.GetIntValue(elem.Id),
                UniqueId = elem.UniqueId,
                Category = elem.Category?.Name ?? "(No Category)",
                ClassName = elem.GetType().Name,
                Name = elem.Name ?? "",
                IsType = isType,
            };

            // Family name
            if (elem is FamilyInstance fi && fi.Symbol?.Family != null)
            {
                entry.FamilyName = fi.Symbol.Family.Name;
                entry.TypeName = fi.Symbol.Name;
            }
            else if (elem is ElementType et)
            {
                entry.TypeName = et.Name;
                // Try to get family name from FamilyName parameter
                var famParam = elem.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME);
                if (famParam != null && famParam.HasValue)
                    entry.FamilyName = famParam.AsString();
            }

            // Level
            var levelParam = elem.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);
            if (levelParam == null)
                levelParam = elem.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (levelParam == null)
                levelParam = elem.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);

            if (levelParam != null && levelParam.HasValue)
            {
                var levelId = levelParam.AsElementId();
                if (levelId != null && levelId != ElementId.InvalidElementId)
                {
                    var level = elem.Document.GetElement(levelId) as Level;
                    if (level != null)
                        entry.LevelName = level.Name;
                }
            }

            // Workset
            if (elem.Document.IsWorkshared)
            {
                var wsParam = elem.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
                if (wsParam != null && wsParam.HasValue)
                    entry.WorksetName = wsParam.AsValueString();
            }

            return entry;
        }

        /// <summary>
        /// Batched extraction: process elements in batches, returning each batch
        /// independently so callers can persist partial results between batches.
        /// If BatchSize is 0 or not set, returns a single batch with all results.
        /// Each batch includes its own element list, counts, and batch metadata.
        /// Uses List instead of yield/IEnumerable to avoid CS1626
        /// (yield not allowed in try blocks with catch clauses).
        /// </summary>
        public List<InventoryBatchOutput> CollectInventoryBatched(
            Document doc, InventoryParameters parameters)
        {
            parameters.ApplyDefaults();

            var batches = new List<InventoryBatchOutput>();
            var categoryFilter = parameters.CategoryFilter != null
                ? new HashSet<string>(parameters.CategoryFilter,
                    StringComparer.OrdinalIgnoreCase)
                : null;
            var levelFilter = parameters.LevelFilter != null
                ? new HashSet<string>(parameters.LevelFilter,
                    StringComparer.OrdinalIgnoreCase)
                : null;

            int batchSize = parameters.BatchSize > 0
                ? parameters.BatchSize : int.MaxValue;
            int skipCount = parameters.SkipElements > 0
                ? parameters.SkipElements : 0;
            int maxElements = parameters.MaxElements > 0
                ? parameters.MaxElements : int.MaxValue;

            int globalProcessed = 0;
            int globalSkipped = 0;
            int batchNumber = 0;
            int batchElementCount = 0;
            var currentBatch = new InventoryOutput();
            var globalCategoryCounts = new Dictionary<string, int>();

            // --- Instance elements ---
            var collector = new FilteredElementCollector(doc)
                .WhereElementIsNotElementType();

            foreach (Element elem in collector)
            {
                if (globalProcessed >= maxElements) break;
                if (elem == null) continue;

                bool processed = ProcessInstanceElement(
                    elem, parameters, categoryFilter, levelFilter,
                    ref globalSkipped, skipCount,
                    currentBatch, globalCategoryCounts);

                if (!processed) continue;

                globalProcessed++;
                batchElementCount++;

                if (batchElementCount >= batchSize)
                {
                    batchNumber++;
                    batches.Add(new InventoryBatchOutput
                    {
                        BatchNumber = batchNumber,
                        Output = currentBatch,
                        IsLastBatch = false,
                        GlobalElementsProcessed = globalProcessed,
                        GlobalCategoryCounts = new Dictionary<string, int>(globalCategoryCounts),
                    });
                    currentBatch = new InventoryOutput();
                    batchElementCount = 0;
                }
            }

            // --- Type elements ---
            var typeCollector = new FilteredElementCollector(doc)
                .WhereElementIsElementType();

            foreach (Element typeElem in typeCollector)
            {
                if (globalProcessed >= maxElements) break;
                if (typeElem == null) continue;

                bool processed = ProcessTypeElement(
                    typeElem, parameters, categoryFilter,
                    currentBatch, globalCategoryCounts);

                if (!processed) continue;

                globalProcessed++;
                batchElementCount++;

                if (batchElementCount >= batchSize)
                {
                    batchNumber++;
                    batches.Add(new InventoryBatchOutput
                    {
                        BatchNumber = batchNumber,
                        Output = currentBatch,
                        IsLastBatch = false,
                        GlobalElementsProcessed = globalProcessed,
                        GlobalCategoryCounts = new Dictionary<string, int>(globalCategoryCounts),
                    });
                    currentBatch = new InventoryOutput();
                    batchElementCount = 0;
                }
            }

            // Final batch (may be partial or the only batch)
            if (batchElementCount > 0 || batchNumber == 0)
            {
                batchNumber++;
                batches.Add(new InventoryBatchOutput
                {
                    BatchNumber = batchNumber,
                    Output = currentBatch,
                    IsLastBatch = true,
                    GlobalElementsProcessed = globalProcessed,
                    GlobalCategoryCounts = new Dictionary<string, int>(globalCategoryCounts),
                    TotalBatches = batchNumber,
                });
            }

            // Mark the last batch
            if (batches.Count > 0)
            {
                var last = batches[batches.Count - 1];
                last.IsLastBatch = true;
                last.TotalBatches = batches.Count;
            }

            return batches;
        }

        /// <summary>Process a single instance element. Returns true if the element was accepted.</summary>
        private bool ProcessInstanceElement(
            Element elem, InventoryParameters parameters,
            HashSet<string> categoryFilter, HashSet<string> levelFilter,
            ref int globalSkipped, int skipCount,
            InventoryOutput currentBatch, Dictionary<string, int> globalCategoryCounts)
        {
            try
            {
                string catName = elem.Category?.Name ?? "(No Category)";

                if (categoryFilter != null && !categoryFilter.Contains(catName))
                    return false;

                if (levelFilter != null)
                {
                    string elemLevel = GetElementLevelName(elem);
                    if (string.IsNullOrEmpty(elemLevel) || !levelFilter.Contains(elemLevel))
                        return false;
                }

                if (globalSkipped < skipCount)
                {
                    globalSkipped++;
                    return false;
                }

                if (!globalCategoryCounts.ContainsKey(catName))
                    globalCategoryCounts[catName] = 0;
                globalCategoryCounts[catName]++;

                if (!currentBatch.CategoryCounts.ContainsKey(catName))
                    currentBatch.CategoryCounts[catName] = 0;
                currentBatch.CategoryCounts[catName]++;
                currentBatch.InstanceCount++;

                if (!parameters.SummaryOnly)
                {
                    var entry = BuildElementEntry(elem, isType: false);
                    if (parameters.IncludeInstanceParameters)
                        entry.Parameters = CollectParameters(elem);
                    currentBatch.Elements.Add(entry);
                }

                return true;
            }
            catch (Exception)
            {
                currentBatch.ErrorCount++;
                return false;
            }
        }

        /// <summary>Process a single type element. Returns true if the element was accepted.</summary>
        private bool ProcessTypeElement(
            Element typeElem, InventoryParameters parameters,
            HashSet<string> categoryFilter,
            InventoryOutput currentBatch, Dictionary<string, int> globalCategoryCounts)
        {
            try
            {
                string catName = typeElem.Category?.Name ?? "(No Category)";

                if (categoryFilter != null && !categoryFilter.Contains(catName))
                    return false;

                string typeCatKey = catName + " (Types)";
                if (!globalCategoryCounts.ContainsKey(typeCatKey))
                    globalCategoryCounts[typeCatKey] = 0;
                globalCategoryCounts[typeCatKey]++;

                if (!currentBatch.CategoryCounts.ContainsKey(typeCatKey))
                    currentBatch.CategoryCounts[typeCatKey] = 0;
                currentBatch.CategoryCounts[typeCatKey]++;
                currentBatch.TypeCount++;

                if (!parameters.SummaryOnly)
                {
                    var entry = BuildElementEntry(typeElem, isType: true);
                    if (parameters.IncludeTypeParameters)
                        entry.Parameters = CollectParameters(typeElem);
                    currentBatch.Elements.Add(entry);
                }

                return true;
            }
            catch (Exception)
            {
                currentBatch.ErrorCount++;
                return false;
            }
        }

        /// <summary>Get the level name for an element, or null if none.</summary>
        private string GetElementLevelName(Element elem)
        {
            var levelParam = elem.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)
                ?? elem.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM)
                ?? elem.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (levelParam != null && levelParam.HasValue)
            {
                var levelId = levelParam.AsElementId();
                if (levelId != null && levelId != ElementId.InvalidElementId)
                {
                    var level = elem.Document.GetElement(levelId) as Level;
                    if (level != null)
                        return level.Name;
                }
            }
            return null;
        }

        private List<ParameterEntry> CollectParameters(Element elem)
        {
            var result = new List<ParameterEntry>();

            foreach (Parameter param in elem.Parameters)
            {
                if (param == null || !param.HasValue) continue;

                var pe = new ParameterEntry
                {
                    Name = param.Definition?.Name ?? "(unknown)",
                    StorageType = param.StorageType.ToString(),
                    IsReadOnly = param.IsReadOnly,
                };

                // Built-in parameter id
                if (param.Definition is InternalDefinition intDef)
                {
                    pe.BuiltInParameterId = intDef.BuiltInParameter.ToString();
                }

                // Value extraction
                switch (param.StorageType)
                {
                    case StorageType.String:
                        pe.ValueString = param.AsString() ?? "";
                        break;
                    case StorageType.Integer:
                        pe.ValueInt = param.AsInteger();
                        pe.ValueString = param.AsValueString() ?? param.AsInteger().ToString();
                        break;
                    case StorageType.Double:
                        pe.ValueDouble = param.AsDouble();
                        pe.ValueString = param.AsValueString() ?? param.AsDouble().ToString();
                        break;
                    case StorageType.ElementId:
                        var eid = param.AsElementId();
                        pe.ValueString = param.AsValueString()
                            ?? (eid != null ? RevitElementIdCompat.GetValue(eid).ToString() : "");
                        pe.ValueInt = eid != null ? RevitElementIdCompat.GetIntValue(eid) : (int?)null;
                        break;
                    default:
                        pe.ValueString = param.AsValueString() ?? "";
                        break;
                }

                result.Add(pe);
            }

            return result;
        }

        /// <summary>
        /// Schema discovery: collect parameter definitions/metadata without
        /// extracting values from every element. Much lighter than full
        /// parameter extraction — iterates elements but only reads parameter
        /// Definition objects (name, storage type, read-only, built-in ID).
        /// Optionally collects limited value samples per parameter.
        /// </summary>
        public SchemaOutput CollectSchema(
            Document doc, InventoryParameters parameters)
        {
            parameters.ApplyDefaults();

            var schema = new SchemaOutput();
            var seenParams = new Dictionary<string, ParameterSchemaEntry>(
                StringComparer.OrdinalIgnoreCase);
            var categoryFilter = parameters.CategoryFilter != null
                ? new HashSet<string>(parameters.CategoryFilter,
                    StringComparer.OrdinalIgnoreCase)
                : null;
            var levelFilter = parameters.LevelFilter != null
                ? new HashSet<string>(parameters.LevelFilter,
                    StringComparer.OrdinalIgnoreCase)
                : null;
            int sampleLimit = parameters.SampleValues
                ? (parameters.SampleLimit > 0 ? parameters.SampleLimit : 10)
                : 0;

            int processed = 0;
            int batchSize = parameters.BatchSize > 0
                ? parameters.BatchSize : int.MaxValue;

            // Instance elements
            var collector = new FilteredElementCollector(doc)
                .WhereElementIsNotElementType();

            foreach (Element elem in collector)
            {
                if (processed >= batchSize) break;
                if (elem == null) continue;

                try
                {
                    string catName = elem.Category?.Name ?? "(No Category)";
                    if (categoryFilter != null && !categoryFilter.Contains(catName))
                        continue;
                    if (levelFilter != null)
                    {
                        string elemLevel = GetElementLevelName(elem);
                        if (string.IsNullOrEmpty(elemLevel) || !levelFilter.Contains(elemLevel))
                            continue;
                    }

                    if (!schema.CategoryCounts.ContainsKey(catName))
                        schema.CategoryCounts[catName] = 0;
                    schema.CategoryCounts[catName]++;
                    schema.InstanceCount++;

                    CollectParameterSchema(elem, catName, elem.GetType().Name,
                        false, seenParams, sampleLimit);
                    processed++;
                }
                catch (Exception)
                {
                    schema.ErrorCount++;
                }
            }

            // Type elements
            var typeCollector = new FilteredElementCollector(doc)
                .WhereElementIsElementType();

            foreach (Element typeElem in typeCollector)
            {
                if (processed >= batchSize) break;
                if (typeElem == null) continue;

                try
                {
                    string catName = typeElem.Category?.Name ?? "(No Category)";
                    if (categoryFilter != null && !categoryFilter.Contains(catName))
                        continue;

                    string typeCatKey = catName + " (Types)";
                    if (!schema.CategoryCounts.ContainsKey(typeCatKey))
                        schema.CategoryCounts[typeCatKey] = 0;
                    schema.CategoryCounts[typeCatKey]++;
                    schema.TypeCount++;

                    CollectParameterSchema(typeElem, catName, typeElem.GetType().Name,
                        true, seenParams, sampleLimit);
                    processed++;
                }
                catch (Exception)
                {
                    schema.ErrorCount++;
                }
            }

            schema.Parameters = new List<ParameterSchemaEntry>(seenParams.Values);
            return schema;
        }

        /// <summary>
        /// Collect parameter schema entries from one element. Merges into
        /// the seen dictionary, incrementing observed_count and adding
        /// categories/classes. Optionally collects limited value samples.
        /// </summary>
        private void CollectParameterSchema(
            Element elem, string catName, string className,
            bool isType,
            Dictionary<string, ParameterSchemaEntry> seen,
            int sampleLimit)
        {
            foreach (Parameter param in elem.Parameters)
            {
                if (param == null) continue;
                var def = param.Definition;
                if (def == null) continue;
                string paramName = def.Name ?? "(unknown)";
                string key = paramName + "|" + param.StorageType.ToString()
                    + "|" + (isType ? "type" : "instance");

                if (!seen.TryGetValue(key, out var entry))
                {
                    entry = new ParameterSchemaEntry
                    {
                        ParameterName = paramName,
                        StorageType = param.StorageType.ToString(),
                        IsReadOnly = param.IsReadOnly,
                        IsInstanceParam = !isType,
                        IsTypeParam = isType,
                    };
                    if (def is InternalDefinition intDef)
                    {
                        entry.BuiltInParameterId = intDef.BuiltInParameter.ToString();
                    }

                    // Enriched metadata from Definition
                    try
                    {
                        var dataType = def.GetDataType();
                        if (dataType != null)
                        {
                            entry.DataTypeId = dataType.TypeId ?? "";
                            try { entry.DataTypeLabel = LabelUtils.GetLabelForSpec(dataType) ?? ""; }
                            catch { entry.DataTypeLabel = ""; }

                            try { entry.IsMeasurableSpec = UnitUtils.IsMeasurableSpec(dataType); }
                            catch { entry.IsMeasurableSpec = false; }

                            if (entry.IsMeasurableSpec)
                            {
                                try
                                {
                                    var discipline = UnitUtils.GetDiscipline(dataType);
                                    if (discipline != null)
                                    {
                                        entry.DisciplineLabel = LabelUtils.GetLabelForDiscipline(discipline) ?? "";
                                    }
                                }
                                catch { entry.DisciplineLabel = ""; }

                                try
                                {
                                    var validUnits = UnitUtils.GetValidUnits(dataType);
                                    if (validUnits != null && validUnits.Count > 0)
                                    {
                                        var firstUnit = validUnits[0];
                                        entry.UnitTypeId = firstUnit.TypeId ?? "";
                                        try { entry.UnitLabel = LabelUtils.GetLabelForUnit(firstUnit) ?? ""; }
                                        catch { entry.UnitLabel = ""; }
                                    }
                                }
                                catch { /* unit resolution not critical */ }
                            }
                        }
                    }
                    catch { /* data type resolution not critical */ }

                    try
                    {
                        var groupType = def.GetGroupTypeId();
                        if (groupType != null)
                        {
                            entry.GroupTypeId = groupType.TypeId ?? "";
                            try { entry.GroupTypeLabel = LabelUtils.GetLabelForGroup(groupType) ?? ""; }
                            catch { entry.GroupTypeLabel = ""; }
                        }
                    }
                    catch { /* group type resolution not critical */ }

                    seen[key] = entry;
                }

                entry.ObservedCount++;
                if (!entry.ObservedOnCategories.Contains(catName))
                    entry.ObservedOnCategories.Add(catName);
                if (!entry.ObservedOnClasses.Contains(className))
                    entry.ObservedOnClasses.Add(className);

                // Collect limited value samples if requested
                if (sampleLimit > 0 && param.HasValue)
                {
                    int currentSamples = entry.SampleValueStrings.Count
                        + entry.SampleValueNumbers.Count;
                    if (currentSamples < sampleLimit)
                    {
                        try
                        {
                            string vs = param.AsValueString();
                            if (!string.IsNullOrEmpty(vs)
                                && !entry.SampleValueStrings.Contains(vs))
                            {
                                entry.SampleValueStrings.Add(vs);
                            }
                            if (param.StorageType == StorageType.Double)
                            {
                                double dv = param.AsDouble();
                                if (!entry.SampleValueNumbers.Contains(dv))
                                    entry.SampleValueNumbers.Add(dv);
                            }
                            else if (param.StorageType == StorageType.Integer)
                            {
                                double iv = param.AsInteger();
                                if (!entry.SampleValueNumbers.Contains(iv))
                                    entry.SampleValueNumbers.Add(iv);
                            }
                        }
                        catch (Exception)
                        {
                            // Skip value sampling errors silently
                        }
                    }
                }
            }
        }
    }

    // ---- Data transfer objects ----

    public class InventoryOutput
    {
        public List<ElementEntry> Elements { get; set; } = new List<ElementEntry>();
        public Dictionary<string, int> CategoryCounts { get; set; } = new Dictionary<string, int>();
        public int InstanceCount { get; set; }
        public int TypeCount { get; set; }
        public int ErrorCount { get; set; }
    }

    /// <summary>Wraps a single batch from paginated inventory extraction.</summary>
    public class InventoryBatchOutput
    {
        public int BatchNumber { get; set; }
        public InventoryOutput Output { get; set; }
        public bool IsLastBatch { get; set; }
        public int GlobalElementsProcessed { get; set; }
        public Dictionary<string, int> GlobalCategoryCounts { get; set; } = new Dictionary<string, int>();
        public int TotalBatches { get; set; }
    }

    public class ElementEntry
    {
        public int ElementId { get; set; }
        public string UniqueId { get; set; }
        public string Category { get; set; }
        public string ClassName { get; set; }
        public string Name { get; set; }
        public string FamilyName { get; set; }
        public string TypeName { get; set; }
        public string LevelName { get; set; }
        public string WorksetName { get; set; }
        public bool IsType { get; set; }
        public List<ParameterEntry> Parameters { get; set; } = new List<ParameterEntry>();
    }

    public class ParameterEntry
    {
        public string Name { get; set; }
        public string StorageType { get; set; }
        public string ValueString { get; set; }
        public double? ValueDouble { get; set; }
        public int? ValueInt { get; set; }
        public string BuiltInParameterId { get; set; }
        public bool IsReadOnly { get; set; }
    }

    /// <summary>Output from schema discovery mode.</summary>
    public class SchemaOutput
    {
        public Dictionary<string, int> CategoryCounts { get; set; } = new Dictionary<string, int>();
        public int InstanceCount { get; set; }
        public int TypeCount { get; set; }
        public int ErrorCount { get; set; }
        public List<ParameterSchemaEntry> Parameters { get; set; } = new List<ParameterSchemaEntry>();
    }

    /// <summary>A unique parameter definition discovered during schema scan.</summary>
    public class ParameterSchemaEntry
    {
        public string ParameterName { get; set; }
        public string BuiltInParameterId { get; set; }
        public string StorageType { get; set; }
        public bool IsReadOnly { get; set; }
        public bool IsInstanceParam { get; set; }
        public bool IsTypeParam { get; set; }
        public int ObservedCount { get; set; }
        public List<string> ObservedOnCategories { get; set; } = new List<string>();
        public List<string> ObservedOnClasses { get; set; } = new List<string>();
        public List<string> SampleValueStrings { get; set; } = new List<string>();
        public List<double> SampleValueNumbers { get; set; } = new List<double>();

        // Enriched metadata from Revit API
        public string DataTypeId { get; set; }
        public string DataTypeLabel { get; set; }
        public string GroupTypeId { get; set; }
        public string GroupTypeLabel { get; set; }
        public bool IsMeasurableSpec { get; set; }
        public string UnitTypeId { get; set; }
        public string UnitLabel { get; set; }
        public string DisciplineLabel { get; set; }
    }
}

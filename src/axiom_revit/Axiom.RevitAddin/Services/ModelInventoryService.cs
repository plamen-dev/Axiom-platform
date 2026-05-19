using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Axiom.Core.Models;

namespace Axiom.RevitAddin.Services
{
    /// <summary>
    /// Read-only service that inventories elements and parameters from
    /// the active Revit model. No transactions, no model modifications.
    /// </summary>
    public class ModelInventoryService
    {
        /// <summary>
        /// Scan the model and return structured element/parameter data.
        /// </summary>
        public InventoryOutput CollectInventory(
            Document doc, InventoryParameters parameters)
        {
            var output = new InventoryOutput();
            var categoryFilter = parameters.CategoryFilter != null
                ? new HashSet<string>(parameters.CategoryFilter,
                    StringComparer.OrdinalIgnoreCase)
                : null;

            // Collect all elements (instances)
            var collector = new FilteredElementCollector(doc)
                .WhereElementIsNotElementType();

            foreach (Element elem in collector)
            {
                if (elem == null) continue;
                string catName = elem.Category?.Name ?? "(No Category)";

                if (categoryFilter != null && !categoryFilter.Contains(catName))
                    continue;

                var entry = BuildElementEntry(elem, isType: false);
                if (parameters.IncludeInstanceParameters)
                    entry.Parameters = CollectParameters(elem);

                output.Elements.Add(entry);
            }

            // Collect element types
            var typeCollector = new FilteredElementCollector(doc)
                .WhereElementIsElementType();

            foreach (Element typeElem in typeCollector)
            {
                if (typeElem == null) continue;
                string catName = typeElem.Category?.Name ?? "(No Category)";

                if (categoryFilter != null && !categoryFilter.Contains(catName))
                    continue;

                var entry = BuildElementEntry(typeElem, isType: true);
                if (parameters.IncludeTypeParameters)
                    entry.Parameters = CollectParameters(typeElem);

                output.Elements.Add(entry);
            }

            return output;
        }

        private ElementEntry BuildElementEntry(Element elem, bool isType)
        {
            var entry = new ElementEntry
            {
                ElementId = elem.Id.IntegerValue,
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
                        pe.ValueString = param.AsValueString() ?? eid?.IntegerValue.ToString() ?? "";
                        pe.ValueInt = eid?.IntegerValue;
                        break;
                    default:
                        pe.ValueString = param.AsValueString() ?? "";
                        break;
                }

                result.Add(pe);
            }

            return result;
        }
    }

    // ---- Data transfer objects ----

    public class InventoryOutput
    {
        public List<ElementEntry> Elements { get; set; } = new List<ElementEntry>();
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
}

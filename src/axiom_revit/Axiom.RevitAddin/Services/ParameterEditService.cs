using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Axiom.Core.Compat;

namespace Axiom.RevitAddin.Services
{
    /// <summary>
    /// Low-level service for reading and writing Revit element parameters.
    /// Used by SetParameterValueCapability. No transaction management —
    /// the caller (capability or PromptCommand) owns the transaction.
    /// </summary>
    public class ParameterEditService
    {
        /// <summary>
        /// Result for a single element parameter operation.
        /// </summary>
        public class ElementEditResult
        {
            public long ElementId { get; set; }
            public string Category { get; set; } = "";
            public string OldValue { get; set; } = "";
            public string NewValue { get; set; } = "";
            public string Status { get; set; } = "preview";
            public string ErrorMessage { get; set; }
        }

        /// <summary>
        /// Collect elements of the given category, optionally filtered to
        /// the active view. Returns at most <paramref name="maxCount"/> elements.
        /// </summary>
        public List<Element> CollectElements(
            Document doc,
            string categoryName,
            int maxCount,
            bool activeViewOnly)
        {
            // Resolve category by display name — returns the Category object
            // directly so we never need to cast to BuiltInCategory (avoids
            // Int32/Int64 mismatch on Revit 2027 where ElementId.Value is long).
            Category matchedCategory = ResolveCategoryByName(doc, categoryName);

            var collector = activeViewOnly && doc.ActiveView != null
                ? new FilteredElementCollector(doc, doc.ActiveView.Id)
                : new FilteredElementCollector(doc);

            if (matchedCategory != null)
            {
                // Use ElementCategoryFilter with the Category's ElementId —
                // no BuiltInCategory enum cast required.
                collector = collector
                    .WherePasses(new ElementCategoryFilter(matchedCategory.Id))
                    .WhereElementIsNotElementType();
            }
            else
            {
                // Fallback: filter by category name string comparison
                collector = collector.WhereElementIsNotElementType();
                var all = collector.ToElements();
                return all
                    .Where(e => e.Category != null &&
                           string.Equals(e.Category.Name, categoryName,
                               StringComparison.OrdinalIgnoreCase))
                    .Take(maxCount)
                    .ToList();
            }

            return collector.ToElements().Take(maxCount).ToList();
        }

        /// <summary>
        /// Resolve a specific set of elements by their numeric IDs. Used by
        /// the interactive preview→apply flow so Apply targets exactly the
        /// elements that were previewed — never a recollected set. Any ID
        /// that no longer resolves (deleted/changed since preview) is reported
        /// via <paramref name="missingIds"/> so the caller can block Apply.
        /// </summary>
        public List<Element> CollectElementsByIds(
            Document doc,
            IEnumerable<long> elementIds,
            out List<long> missingIds)
        {
            missingIds = new List<long>();
            var elements = new List<Element>();

            if (elementIds == null)
                return elements;

            foreach (long idValue in elementIds)
            {
                ElementId eid = RevitElementIdCompat.FromLong(idValue);
                Element e = doc.GetElement(eid);
                if (e == null)
                    missingIds.Add(idValue);
                else
                    elements.Add(e);
            }

            return elements;
        }

        /// <summary>
        /// Preview: read current parameter values without modifying anything.
        /// </summary>
        public List<ElementEditResult> Preview(
            List<Element> elements,
            string parameterName,
            string newValue)
        {
            var results = new List<ElementEditResult>();
            foreach (var elem in elements)
            {
                var r = new ElementEditResult
                {
                    ElementId = RevitElementIdCompat.GetValue(elem.Id),
                    Category = elem.Category?.Name ?? "",
                    NewValue = newValue,
                    Status = "preview"
                };

                Parameter param = FindParameter(elem, parameterName);
                if (param == null)
                {
                    r.Status = "skipped";
                    r.ErrorMessage = $"Parameter '{parameterName}' not found on element.";
                    r.OldValue = "(not found)";
                }
                else if (param.IsReadOnly)
                {
                    r.Status = "skipped";
                    r.ErrorMessage = $"Parameter '{parameterName}' is read-only.";
                    r.OldValue = param.AsString() ?? param.AsValueString() ?? "";
                }
                else if (param.StorageType != StorageType.String)
                {
                    r.Status = "skipped";
                    r.ErrorMessage = $"Parameter '{parameterName}' is not a text parameter (StorageType={param.StorageType}).";
                    r.OldValue = param.AsValueString() ?? "";
                }
                else
                {
                    r.OldValue = param.AsString() ?? "";
                }

                results.Add(r);
            }
            return results;
        }

        /// <summary>
        /// Apply: set parameter values on elements. Caller must have an
        /// active transaction. Returns per-element results.
        /// </summary>
        public List<ElementEditResult> Apply(
            List<Element> elements,
            string parameterName,
            string newValue)
        {
            var results = new List<ElementEditResult>();
            foreach (var elem in elements)
            {
                var r = new ElementEditResult
                {
                    ElementId = RevitElementIdCompat.GetValue(elem.Id),
                    Category = elem.Category?.Name ?? "",
                    NewValue = newValue
                };

                Parameter param = FindParameter(elem, parameterName);
                if (param == null)
                {
                    r.Status = "failed";
                    r.ErrorMessage = $"Parameter '{parameterName}' not found on element.";
                    r.OldValue = "(not found)";
                    results.Add(r);
                    continue;
                }

                if (param.IsReadOnly)
                {
                    r.Status = "failed";
                    r.ErrorMessage = $"Parameter '{parameterName}' is read-only.";
                    r.OldValue = param.AsString() ?? param.AsValueString() ?? "";
                    results.Add(r);
                    continue;
                }

                if (param.StorageType != StorageType.String)
                {
                    r.Status = "failed";
                    r.ErrorMessage = $"Parameter '{parameterName}' is not a text parameter.";
                    r.OldValue = param.AsValueString() ?? "";
                    results.Add(r);
                    continue;
                }

                r.OldValue = param.AsString() ?? "";
                try
                {
                    param.Set(newValue);
                    r.Status = "success";
                }
                catch (Exception ex)
                {
                    r.Status = "failed";
                    r.ErrorMessage = ex.Message;
                }

                results.Add(r);
            }
            return results;
        }

        /// <summary>
        /// Find a parameter on an element by name (case-insensitive).
        /// Prefers instance parameters over type parameters.
        /// </summary>
        private static Parameter FindParameter(Element elem, string name)
        {
            // Search instance parameters first
            foreach (Parameter p in elem.Parameters)
            {
                if (string.Equals(p.Definition?.Name, name,
                    StringComparison.OrdinalIgnoreCase))
                {
                    return p;
                }
            }
            return null;
        }

        /// <summary>
        /// Resolve a category display name to a Revit Category object.
        /// Returns the Category directly — no BuiltInCategory enum cast,
        /// which avoids Int32/Int64 type mismatches on Revit 2027.
        /// </summary>
        private static Category ResolveCategoryByName(
            Document doc, string categoryName)
        {
            // Exact match first
            foreach (Category cat in doc.Settings.Categories)
            {
                if (string.Equals(cat.Name, categoryName,
                    StringComparison.OrdinalIgnoreCase))
                {
                    return cat;
                }
            }

            // Try common singular/plural normalization
            string singular = categoryName.TrimEnd('s');
            string plural = categoryName + "s";
            foreach (Category cat in doc.Settings.Categories)
            {
                string catName = cat.Name;
                if (string.Equals(catName, singular, StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(catName, plural, StringComparison.OrdinalIgnoreCase))
                {
                    return cat;
                }
            }

            return null;
        }
    }
}

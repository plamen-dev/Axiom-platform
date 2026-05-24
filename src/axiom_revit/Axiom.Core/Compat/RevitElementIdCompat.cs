using Autodesk.Revit.DB;

namespace Axiom.Core.Compat
{
    /// <summary>
    /// Version-safe helper for ElementId value access.
    ///
    /// Revit 2024 (.NET 4.8): ElementId.IntegerValue returns int.
    /// Revit 2027 (.NET 10):  ElementId.IntegerValue removed; use ElementId.Value (long).
    ///
    /// Usage: RevitElementIdCompat.GetValue(elementId)
    /// </summary>
    public static class RevitElementIdCompat
    {
        /// <summary>
        /// Returns the numeric value of an ElementId as a long.
        /// Safe across Revit 2024 and 2027.
        /// </summary>
        public static long GetValue(ElementId id)
        {
            if (id == null) return -1;
#if REVIT_2027
            return id.Value;
#else
            return id.IntegerValue;
#endif
        }

        /// <summary>
        /// Returns the numeric value as an int (for backward compatibility).
        /// Truncates on Revit 2027 if the value exceeds int range — unlikely
        /// in practice since Revit element IDs are well within int range.
        /// </summary>
        public static int GetIntValue(ElementId id)
        {
            return (int)GetValue(id);
        }
    }
}

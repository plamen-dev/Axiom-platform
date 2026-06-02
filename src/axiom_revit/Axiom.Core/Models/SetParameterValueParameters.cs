using System.Collections.Generic;

namespace Axiom.Core.Models
{
    /// <summary>
    /// Parameters for the SetParameterValue capability.
    /// Constrains edits to text instance parameters within a single category.
    /// </summary>
    public class SetParameterValueParameters
    {
        /// <summary>Revit category to filter (e.g. "Walls", "Doors"). Required.</summary>
        public string Category { get; set; }

        /// <summary>Parameter name to set (e.g. "Comments", "Mark"). Required.</summary>
        public string ParameterName { get; set; }

        /// <summary>New value to assign. Text only in v0.</summary>
        public string Value { get; set; }

        /// <summary>Maximum number of elements to modify. Hard cap: 5 in v0.</summary>
        public int ElementCount { get; set; }

        /// <summary>"preview" = dry-run (no model modification), "apply" = live edit.</summary>
        public string Mode { get; set; } = "preview";

        /// <summary>If true, restrict to elements visible in the active view.</summary>
        public bool ActiveViewOnly { get; set; } = true;

        /// <summary>Raw prompt text for evidence tracing.</summary>
        public string RawPrompt { get; set; } = "";

        /// <summary>
        /// Explicit element IDs to edit. When non-empty, the capability
        /// targets exactly these elements (resolved by ID) instead of
        /// re-collecting by category. Used by the interactive preview→apply
        /// flow so Apply edits the exact elements shown in the preview and
        /// never silently recollects a different set if the model/view changed.
        /// </summary>
        public List<long> ElementIds { get; set; }
    }
}

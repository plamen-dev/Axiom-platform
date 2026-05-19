namespace Axiom.Core.Models
{
    /// <summary>
    /// Parameters for the InventoryModel capability.
    /// Currently empty — the capability scans the full model.
    /// Future: add optional category/class filters.
    /// </summary>
    public class InventoryParameters
    {
        /// <summary>Optional category filter (e.g. "Walls", "Levels"). Null = all.</summary>
        public string[] CategoryFilter { get; set; }

        /// <summary>If true, include element type parameters. Default true.</summary>
        public bool IncludeTypeParameters { get; set; } = true;

        /// <summary>If true, include instance parameters. Default true.</summary>
        public bool IncludeInstanceParameters { get; set; } = true;
    }
}

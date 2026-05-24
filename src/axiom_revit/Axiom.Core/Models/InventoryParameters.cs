namespace Axiom.Core.Models
{
    /// <summary>
    /// Parameters for the InventoryModel capability.
    /// Default mode is summary-only (counts + categories, no parameter dump).
    /// Full/detailed scans require explicit opt-in.
    /// </summary>
    public class InventoryParameters
    {
        /// <summary>Optional category filter (e.g. "Walls", "Levels"). Null = all.</summary>
        public string[] CategoryFilter { get; set; }

        /// <summary>Optional level filter (e.g. "Level 1"). Null = all levels.</summary>
        public string[] LevelFilter { get; set; }

        /// <summary>If true, include element type parameters. Default false (summary-only).</summary>
        public bool IncludeTypeParameters { get; set; } = false;

        /// <summary>If true, include instance parameters. Default false (summary-only).</summary>
        public bool IncludeInstanceParameters { get; set; } = false;

        /// <summary>Shorthand to enable/disable all parameter collection. Overrides type/instance flags when set.</summary>
        public bool? IncludeParameters { get; set; }

        /// <summary>If true, only collect counts and category breakdown — no element details or parameters.</summary>
        public bool SummaryOnly { get; set; } = true;

        /// <summary>Max elements to process. 0 or negative = no limit. Default 0.</summary>
        public int MaxElements { get; set; } = 0;

        /// <summary>Batch size for paginated extraction. 0 = no batching (single pass). When > 0,
        /// elements are processed in batches of this size and each batch is saved independently
        /// so partial results survive crashes.</summary>
        public int BatchSize { get; set; } = 0;

        /// <summary>Number of elements to skip before processing (offset for manual pagination).
        /// Used when resuming from a specific batch. Default 0.</summary>
        public int SkipElements { get; set; } = 0;

        /// <summary>If true, collect element/class/category inventory without parameters.
        /// Output: ElementId, Category, ClassName, Name, LevelName, IsType.
        /// Safe for whole-model scans. Previously called "schema".</summary>
        public bool SchemaOnly { get; set; } = false;

        /// <summary>If true, collect parameter definitions/metadata per element — no values.
        /// Output: ParameterName, StorageType, BuiltInParameterId, IsReadOnly, Instance/Type,
        /// ObservedCount, ObservedOnCategories, ObservedOnClasses.
        /// Uses CollectSchema() which reads only param.Definition objects.</summary>
        public bool ParameterSchemaOnly { get; set; } = false;

        /// <summary>If true, collect limited value samples per parameter instead of all values.
        /// Caps samples per parameter to SampleLimit.</summary>
        public bool SampleValues { get; set; } = false;

        /// <summary>Max value samples per parameter when SampleValues is true. Default 10.</summary>
        public int SampleLimit { get; set; } = 10;

        /// <summary>Scan mode label for dialog/logging: summary, schema, sample_values, category, sample, full.</summary>
        public string ScanMode { get; set; } = "summary";

        /// <summary>Apply IncludeParameters shorthand to type/instance flags.</summary>
        public void ApplyDefaults()
        {
            if (IncludeParameters.HasValue)
            {
                IncludeTypeParameters = IncludeParameters.Value;
                IncludeInstanceParameters = IncludeParameters.Value;
            }
        }
    }
}

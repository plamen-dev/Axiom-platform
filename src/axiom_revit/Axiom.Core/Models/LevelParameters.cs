namespace Axiom.Core.Models
{
    /// <summary>
    /// Holds all parameters required to create building levels.
    /// This class is Revit-agnostic by design.
    /// </summary>
    public class LevelParameters
    {
        public int LevelCount { get; set; }
        public double FloorToFloorFeet { get; set; }
        public double StartElevationFeet { get; set; }

        /// <summary>
        /// Optional custom names for levels (e.g., "Basement", "Ground", "Level 2").
        /// When provided, length must match LevelCount.
        /// </summary>
        public string[] LevelNames { get; set; }

        /// <summary>
        /// Optional explicit elevation for each level.
        /// When provided, overrides FloorToFloorFeet calculation.
        /// Length must match LevelCount.
        /// </summary>
        public double[] VariableElevationsFeet { get; set; }
    }
}

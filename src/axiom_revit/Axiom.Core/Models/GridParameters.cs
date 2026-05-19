namespace Axiom.Core.Models
{
    /// <summary>
    /// Holds all parameters required to create a grid system.
    /// This class is Revit-agnostic by design.
    ///
    /// Parameter model reference:
    ///   Scenarios_and_Parameter_Models/Parameter_Models/revit_grid_parameter_model_001.txt
    /// </summary>
    public class GridParameters
    {
        public int HorizontalCount { get; set; }
        public int VerticalCount { get; set; }
        public double SpacingFeet { get; set; }
        public string Naming { get; set; }
        public double Length { get; set; }

        /// <summary>
        /// Optional per-bay spacings for vertical (numeric) grids.
        /// When provided, overrides SpacingFeet for the vertical direction.
        /// Array length must equal HorizontalCount - 1.
        /// </summary>
        public double[] HorizontalSpacingsFeet { get; set; }

        /// <summary>
        /// Optional per-bay spacings for horizontal (alphabetic) grids.
        /// When provided, overrides SpacingFeet for the horizontal direction.
        /// Array length must equal VerticalCount - 1.
        /// </summary>
        public double[] VerticalSpacingsFeet { get; set; }
    }
}

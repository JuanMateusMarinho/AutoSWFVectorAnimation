package {
    import flash.display.MovieClip;
    import flash.events.Event;
    import flash.geom.ColorTransform;
    import flash.geom.Matrix;
    import flash.system.ApplicationDomain;

    /** Stands in for AQW's mcSkel (the avatar's mcChar): one empty clip per slot with the real names and z-order, the
     *  head slot holding hair and helm, the optional slots hidden and the back limbs tinted black as the client does.
     *  It replays where the real skeleton puts its head slot on each frame of a game label (AutoSWF measures it from
     *  the user's cached client). */
    public dynamic class AutoSWFSkeleton extends MovieClip {
        public static const OPTIONAL:Array = ["cape", "backhair", "robe", "backrobe", "pvpFlag", "weapon", "weaponOff",
            "weaponFist", "weaponFistOff", "shield"];
        public static const TINTED:Array = ["backshoulder", "backfoot", "backthigh", "backshin"];
        public static const PARTS:Object = {Chest: ["chest"], Hip: ["hip"], FootIdle: ["idlefoot"],
            Foot: ["frontfoot", "backfoot"], Shoulder: ["frontshoulder", "backshoulder"], Hand: ["fronthand", "backhand"],
            Thigh: ["frontthigh", "backthigh"], Shin: ["frontshin", "backshin"], Robe: ["robe"], RobeBack: ["backrobe"]};

        public var avatar:AutoSWFAvatar;
        public var head:MovieClip;
        public var paused:Boolean = false;
        private var tracks:Object;
        private var track:Object;
        private var index:int = 0;

        public function AutoSWFSkeleton(avatar:AutoSWFAvatar, slots:Array, tracks:Object) {
            super();
            this.avatar = avatar;
            this.tracks = tracks;
            name = "mcChar";
            for each (var slotName:String in slots) {
                var slot:MovieClip = new MovieClip();
                slot.name = slotName;
                this[slotName] = slot;
                addChild(slot);
                if (OPTIONAL.indexOf(slotName) >= 0) slot.visible = false;
                if (TINTED.indexOf(slotName) >= 0) slot.transform.colorTransform = new ColorTransform(0, 0, 0, 1);
            }
            head = this["head"] as MovieClip;
            for each (var partName:String in ["hair", "helm"]) {
                var part:MovieClip = new MovieClip();
                part.name = partName;
                head[partName] = part;
                head.addChild(part);
            }
            addEventListener(Event.ENTER_FRAME, onFrame);
        }

        /** Puts the armor's part classes in their slots and its head in place of the face, as the client does; returns
         *  the head (its code runs when it reaches the stage). */
        public function wear(domain:ApplicationDomain, link:String, gender:String):MovieClip {
            for (var part:String in PARTS) {
                var className:String = link + gender + part;
                if (!domain.hasDefinition(className)) continue;
                var Piece:Class = domain.getDefinition(className) as Class;
                for each (var slotName:String in PARTS[part]) {
                    var slot:MovieClip = this[slotName] as MovieClip;
                    if (slot == null) continue;
                    var piece:MovieClip = new Piece() as MovieClip;
                    slot.addChildAt(piece, 0);
                    if (slotName == "backhand") piece.transform.colorTransform = new ColorTransform(0, 0, 0, 1);
                    if (part == "Robe" || part == "RobeBack") slot.visible = true;
                }
                if (part == "Foot" && this["frontfoot"] != null) this["frontfoot"].visible = false;
            }
            var Head:Class = domain.getDefinition(link + gender + "Head") as Class;
            var face:MovieClip = new Head() as MovieClip;
            face.name = "face";
            head.addChildAt(face, 0);
            return face;
        }

        /** The skeleton playing a game label: its head slot follows the real skeleton's placement for it. */
        public function playLabel(label:String):void {
            if (tracks[label] == null) return;
            track = tracks[label];
            index = 0;
            place();
        }

        override public function gotoAndPlay(frame:Object, scene:String = null):void {
            if (frame is String) avatar.playLabel(String(frame));
            else super.gotoAndPlay(frame, scene);
        }

        /** The head slot's transform the real skeleton has now ([a, b, c, d, tx, ty]), or null when none plays. */
        public function expectedPlacement():Array {
            return track == null ? null : track.frames[index];
        }

        public function advance():void {
            if (track == null) return;
            if (index + 1 < track.frames.length) index++;
            else if (track.loop) index = 0;
            place();
        }

        private function onFrame(e:Event):void {
            if (!paused) advance();
        }

        private function place():void {
            var f:Array = track.frames[index];
            head.transform.matrix = new Matrix(f[0], f[1], f[2], f[3], f[4], f[5]);
        }
    }
}
